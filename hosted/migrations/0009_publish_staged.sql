-- Publication must match the complete paged claim set that was admitted under
-- this reservation. The service independently verifies every exact object in
-- R2 before calling this function; SQL does not treat pages as storage proof.
CREATE FUNCTION hosted.publish_verified_staged_current(
  p_account_id uuid,
  p_vault_id uuid,
  p_reservation_id uuid,
  p_snapshot_id uuid,
  p_verified_objects jsonb,
  p_current_allowance bigint
) RETURNS boolean LANGUAGE plpgsql AS $$
DECLARE
  v_reservation hosted.upload_reservations%ROWTYPE;
BEGIN
  IF p_account_id IS NULL OR p_vault_id IS NULL OR p_reservation_id IS NULL OR
     p_snapshot_id IS NULL OR
     jsonb_typeof(p_verified_objects) IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'hosted_staged_publication_invalid';
  END IF;
  -- Follow the same lock order as page append and quota reservation. The
  -- staged set cannot change after we have locked its reservation row.
  PERFORM 1 FROM hosted.accounts WHERE account_id = p_account_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'hosted_staged_publication_invalid'; END IF;
  SELECT * INTO v_reservation FROM hosted.upload_reservations
    WHERE reservation_id = p_reservation_id AND account_id = p_account_id
      AND vault_id = p_vault_id FOR UPDATE;
  IF NOT FOUND OR v_reservation.state NOT IN ('active', 'published') OR
     (v_reservation.state = 'active' AND
      v_reservation.expires_at <= clock_timestamp()) OR
     v_reservation.staged_snapshot_id <> p_snapshot_id OR
     v_reservation.staged_count < 3 OR
     jsonb_array_length(p_verified_objects) <> v_reservation.staged_count THEN
    RAISE EXCEPTION 'hosted_staged_publication_invalid';
  END IF;
  IF EXISTS (
      SELECT item.key, item.bytes, item.sha256
        FROM jsonb_to_recordset(p_verified_objects)
          AS item(key text, bytes bigint, sha256 text)
      EXCEPT
      SELECT object_key, object_bytes, sha256
        FROM hosted.staged_receipt_objects
        WHERE reservation_id = p_reservation_id
    ) OR EXISTS (
      SELECT object_key, object_bytes, sha256
        FROM hosted.staged_receipt_objects
        WHERE reservation_id = p_reservation_id
      EXCEPT
      SELECT item.key, item.bytes, item.sha256
        FROM jsonb_to_recordset(p_verified_objects)
          AS item(key text, bytes bigint, sha256 text)
    ) THEN
    RAISE EXCEPTION 'hosted_staged_publication_conflict';
  END IF;
  RETURN hosted.publish_verified_snapshot_current(p_account_id, p_vault_id,
    p_reservation_id, p_snapshot_id, p_verified_objects, p_current_allowance);
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.publish_verified_staged_current(
  uuid, uuid, uuid, uuid, jsonb, bigint
) FROM PUBLIC;
