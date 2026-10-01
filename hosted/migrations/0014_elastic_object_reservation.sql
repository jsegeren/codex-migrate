-- A new snapshot may reuse almost every object in a prior published snapshot.
-- Reserving the whole snapshot would make incremental backups impossible near
-- the allowance. Grow a tiny active reservation only for each distinct PUT
-- grant, under the same account-before-reservation lock and fresh allowance.
CREATE FUNCTION hosted.reserve_object_grant_elastic_current(
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
  v_needed bigint;
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
  SELECT * INTO v_reservation FROM hosted.upload_reservations
    WHERE reservation_id = p_reservation_id AND account_id = p_account_id
      AND vault_id = p_vault_id FOR UPDATE;
  IF NOT FOUND OR v_reservation.state <> 'active' OR
      v_reservation.expires_at <= clock_timestamp() + interval '1 minute'
      THEN RETURN false; END IF;

  SELECT * INTO v_prior FROM hosted.upload_object_grants
    WHERE reservation_id = p_reservation_id AND object_key = p_key;
  IF FOUND THEN
    RETURN v_prior.object_bytes = p_bytes AND v_prior.sha256 = p_sha256 AND
      hosted.reserve_object_grant_current(p_account_id, p_vault_id,
        p_reservation_id, p_key, p_bytes, p_sha256, p_current_allowance);
  END IF;
  IF v_reservation.granted_objects >= 1000000 THEN RETURN false; END IF;

  v_needed := greatest(0,
    v_reservation.granted_bytes + p_bytes - v_reservation.reserved_bytes);
  IF v_needed > 0 THEN
    UPDATE hosted.accounts SET reserved_bytes = reserved_bytes + v_needed
      WHERE account_id = p_account_id AND v_needed::numeric <=
        p_current_allowance::numeric - retained_bytes::numeric -
        reserved_bytes::numeric;
    IF NOT FOUND THEN RETURN false; END IF;
    UPDATE hosted.upload_reservations
      SET reserved_bytes = reserved_bytes + v_needed
      WHERE reservation_id = p_reservation_id;
  END IF;
  IF NOT hosted.reserve_object_grant_current(p_account_id, p_vault_id,
      p_reservation_id, p_key, p_bytes, p_sha256, p_current_allowance) THEN
    -- Never commit an expanded reservation without its exact durable grant.
    RAISE EXCEPTION 'hosted_elastic_grant_failed';
  END IF;
  RETURN true;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.reserve_object_grant_elastic_current(
  uuid, uuid, uuid, text, bigint, text, bigint
) FROM PUBLIC;
