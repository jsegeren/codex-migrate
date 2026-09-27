-- A reserved byte allowance must not mint unlimited distinct object PUTs.
-- This is a server-side ledger, not a client-submitted usage report. Its rows
-- remain available for orphan cleanup and audit after reservation expiry.
ALTER TABLE hosted.upload_reservations
  ADD COLUMN granted_bytes bigint NOT NULL DEFAULT 0
    CHECK (granted_bytes >= 0 AND granted_bytes <= reserved_bytes),
  ADD COLUMN granted_objects integer NOT NULL DEFAULT 0
    CHECK (granted_objects >= 0 AND granted_objects <= 1000003);
--> statement-breakpoint
CREATE TABLE hosted.upload_object_grants (
  reservation_id uuid NOT NULL REFERENCES hosted.upload_reservations (reservation_id),
  object_key text NOT NULL CHECK (length(object_key) <= 300),
  object_bytes bigint NOT NULL CHECK (object_bytes > 0 AND object_bytes <= 100000000),
  sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  granted_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (reservation_id, object_key)
);
--> statement-breakpoint
CREATE FUNCTION hosted.reserve_object_grant_current(
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

  -- Follow the account-before-reservation lock order used by publication.
  -- A fresh subscription allowance cannot be bypassed with an older row.
  UPDATE hosted.accounts SET allowance_bytes = p_current_allowance
    WHERE account_id = p_account_id
    RETURNING retained_bytes, reserved_bytes INTO v_retained, v_reserved;
  IF NOT FOUND OR v_retained::numeric + v_reserved::numeric >
      p_current_allowance::numeric THEN RETURN false; END IF;
  SELECT * INTO v_reservation FROM hosted.upload_reservations
    WHERE reservation_id = p_reservation_id AND account_id = p_account_id
      AND vault_id = p_vault_id FOR UPDATE;
  IF NOT FOUND OR v_reservation.state <> 'active' OR
      v_reservation.expires_at <= clock_timestamp() THEN RETURN false; END IF;

  SELECT * INTO v_prior FROM hosted.upload_object_grants
    WHERE reservation_id = p_reservation_id AND object_key = p_key;
  IF FOUND THEN
    RETURN v_prior.object_bytes = p_bytes AND v_prior.sha256 = p_sha256;
  END IF;
  IF v_reservation.granted_objects >= 1000003 OR
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
REVOKE EXECUTE ON FUNCTION hosted.reserve_object_grant_current(
  uuid, uuid, uuid, text, bigint, text, bigint
) FROM PUBLIC;
