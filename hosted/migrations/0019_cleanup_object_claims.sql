-- A cleanup worker must reserve an orphan key before it may ask R2 to delete
-- it. The claim is durable across a worker crash and blocks every later PUT
-- grant or publication for that key until cleanup has finished. No provider
-- deletion or quota release is performed by this migration.
CREATE TABLE hosted.cleanup_object_claims (
  account_id uuid NOT NULL,
  vault_id uuid NOT NULL,
  object_key text NOT NULL CHECK (length(object_key) <= 300),
  reservation_id uuid NOT NULL REFERENCES hosted.upload_reservations (reservation_id),
  object_bytes bigint NOT NULL CHECK (object_bytes > 0 AND object_bytes <= 100000000),
  sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  claimed_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  PRIMARY KEY (account_id, vault_id, object_key),
  FOREIGN KEY (account_id, vault_id) REFERENCES hosted.vaults (account_id, vault_id),
  CHECK (deleted_at IS NULL OR deleted_at >= claimed_at)
);
--> statement-breakpoint
CREATE FUNCTION hosted.claim_expired_upload_object(
  p_account_id uuid,
  p_vault_id uuid,
  p_reservation_id uuid,
  p_key text
) RETURNS boolean LANGUAGE plpgsql AS $$
DECLARE
  v_reservation hosted.upload_reservations%ROWTYPE;
  v_grant hosted.upload_object_grants%ROWTYPE;
  v_claim hosted.cleanup_object_claims%ROWTYPE;
BEGIN
  IF p_account_id IS NULL OR p_vault_id IS NULL OR
     p_reservation_id IS NULL OR p_key IS NULL THEN RETURN false; END IF;
  -- Grants and publication take the account lock first. This serializes the
  -- orphan decision with both, including after a slow transaction wait.
  PERFORM 1 FROM hosted.accounts WHERE account_id = p_account_id FOR UPDATE;
  IF NOT FOUND THEN RETURN false; END IF;
  SELECT * INTO v_reservation FROM hosted.upload_reservations
    WHERE reservation_id = p_reservation_id AND account_id = p_account_id
      AND vault_id = p_vault_id FOR UPDATE;
  IF NOT FOUND OR v_reservation.state <> 'cleanup_pending' OR
     v_reservation.expires_at > clock_timestamp() - interval '2 minutes' THEN
    RETURN false;
  END IF;
  SELECT * INTO v_grant FROM hosted.upload_object_grants
    WHERE reservation_id = p_reservation_id AND object_key = p_key;
  IF NOT FOUND OR EXISTS (
      SELECT 1 FROM hosted.objects WHERE account_id = p_account_id
        AND vault_id = p_vault_id AND object_key = p_key
    ) OR EXISTS (
      SELECT 1 FROM hosted.upload_object_grants AS other_grant
      JOIN hosted.upload_reservations AS other_reservation
        USING (reservation_id)
      WHERE other_grant.object_key = p_key
        AND other_grant.reservation_id <> p_reservation_id
        AND other_reservation.account_id = p_account_id
        AND other_reservation.vault_id = p_vault_id
        AND other_reservation.expires_at > clock_timestamp() - interval '2 minutes'
    ) THEN RETURN false; END IF;

  SELECT * INTO v_claim FROM hosted.cleanup_object_claims
    WHERE account_id = p_account_id AND vault_id = p_vault_id
      AND object_key = p_key FOR UPDATE;
  IF FOUND THEN
    RETURN v_claim.reservation_id = p_reservation_id AND
      v_claim.object_bytes = v_grant.object_bytes AND
      v_claim.sha256 = v_grant.sha256 AND v_claim.deleted_at IS NULL;
  END IF;
  INSERT INTO hosted.cleanup_object_claims
    (account_id, vault_id, object_key, reservation_id, object_bytes, sha256)
    VALUES (p_account_id, p_vault_id, p_key, p_reservation_id,
            v_grant.object_bytes, v_grant.sha256);
  RETURN true;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.claim_expired_upload_object(
  uuid, uuid, uuid, text
) FROM PUBLIC;
--> statement-breakpoint
-- Replace the existing grant function at the database boundary. Checking in
-- the HTTP coordinator alone would race a cleanup claim between two queries.
CREATE OR REPLACE FUNCTION hosted.reserve_object_grant_current(
  p_account_id uuid,
  p_vault_id uuid,
  p_reservation_id uuid,
  p_key text,
  p_bytes bigint,
  p_sha256 text,
  p_current_allowance bigint
) RETURNS boolean LANGUAGE plpgsql AS $$
DECLARE
  v_prefix text := 'accounts/' || p_account_id::text || '/vaults/' || p_vault_id::text || '/';
  v_relative text;
  v_reservation hosted.upload_reservations%ROWTYPE;
  v_prior hosted.upload_object_grants%ROWTYPE;
  v_retained bigint;
  v_reserved bigint;
BEGIN
  IF p_account_id IS NULL OR p_vault_id IS NULL OR p_reservation_id IS NULL OR
     p_key IS NULL OR length(p_key) > 300 OR
     left(p_key, length(v_prefix)) <> v_prefix OR
     p_bytes IS NULL OR p_bytes <= 0 OR p_bytes > 100000000 OR
     p_sha256 IS NULL OR p_sha256 !~ '^[0-9a-f]{64}$' OR
     p_current_allowance IS NULL OR p_current_allowance <= 0 THEN
    RETURN false;
  END IF;
  v_relative := substring(p_key from length(v_prefix) + 1);
  IF v_relative !~ (
    '^(metadata/[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.json|'
    || 'objects/[0-9a-f]{2}/[0-9a-f]{62}\.cvchunk|'
    || 'manifests/[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.cvmanifest|'
    || 'refs/[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.json)$'
  ) THEN RETURN false; END IF;

  UPDATE hosted.accounts SET allowance_bytes = p_current_allowance
    WHERE account_id = p_account_id
    RETURNING retained_bytes, reserved_bytes INTO v_retained, v_reserved;
  IF NOT FOUND OR v_retained::numeric + v_reserved::numeric >
      p_current_allowance::numeric THEN RETURN false; END IF;
  -- The account lock protects both this check and grant issuance from a
  -- concurrent cleanup claim, including an exact retry of an older grant.
  IF EXISTS (SELECT 1 FROM hosted.cleanup_object_claims
      WHERE account_id = p_account_id AND vault_id = p_vault_id
        AND object_key = p_key) THEN RETURN false; END IF;
  SELECT * INTO v_reservation FROM hosted.upload_reservations
    WHERE reservation_id = p_reservation_id AND account_id = p_account_id
      AND vault_id = p_vault_id FOR UPDATE;
  IF NOT FOUND OR v_reservation.state <> 'active' OR
      v_reservation.expires_at <= clock_timestamp() + interval '1 minute'
      THEN RETURN false; END IF;

  SELECT * INTO v_prior FROM hosted.upload_object_grants
    WHERE reservation_id = p_reservation_id AND object_key = p_key;
  IF FOUND THEN
    RETURN v_prior.object_bytes = p_bytes AND v_prior.sha256 = p_sha256;
  END IF;
  IF v_reservation.granted_objects >= 1000000 OR
     v_reservation.granted_bytes::numeric + p_bytes::numeric >
     v_reservation.reserved_bytes::numeric THEN RETURN false; END IF;
  INSERT INTO hosted.upload_object_grants
    (reservation_id, object_key, object_bytes, sha256)
    VALUES (p_reservation_id, p_key, p_bytes, p_sha256);
  UPDATE hosted.upload_reservations SET
    granted_bytes = granted_bytes + p_bytes,
    granted_objects = granted_objects + 1
    WHERE reservation_id = p_reservation_id;
  RETURN true;
END;
$$;
--> statement-breakpoint
-- Publication already holds the account lock. This trigger makes even a
-- direct lower-level publication attempt fail while a deletion claim exists.
CREATE FUNCTION hosted.reject_claimed_object_publication()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  PERFORM 1 FROM hosted.accounts WHERE account_id = NEW.account_id FOR UPDATE;
  IF EXISTS (SELECT 1 FROM hosted.cleanup_object_claims
      WHERE account_id = NEW.account_id AND vault_id = NEW.vault_id
        AND object_key = NEW.object_key) THEN
    RAISE EXCEPTION 'hosted_cleanup_object_claimed';
  END IF;
  RETURN NEW;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.reject_claimed_object_publication()
  FROM PUBLIC;
--> statement-breakpoint
CREATE TRIGGER reject_claimed_object_publication
  BEFORE INSERT ON hosted.objects FOR EACH ROW
  EXECUTE FUNCTION hosted.reject_claimed_object_publication();
