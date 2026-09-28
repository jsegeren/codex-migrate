-- Return the captured publication base in the same database statement that
-- creates the reservation. A follow-up read would be a second failure point
-- after quota was already reserved and could not be an atomic receipt.
CREATE FUNCTION hosted.reserve_upload_with_base_current(
  p_account_id uuid,
  p_vault_id uuid,
  p_reservation_id uuid,
  p_bytes bigint,
  p_expires_at timestamptz,
  p_current_allowance bigint
) RETURNS TABLE (allowed boolean, base_snapshot_id uuid)
  LANGUAGE plpgsql AS $$
DECLARE
  v_allowed boolean;
  v_base uuid;
BEGIN
  v_allowed := hosted.reserve_upload_current(p_account_id, p_vault_id,
    p_reservation_id, p_bytes, p_expires_at, p_current_allowance);
  IF v_allowed THEN
    SELECT reservation.base_snapshot_id INTO v_base
      FROM hosted.upload_reservations AS reservation
      WHERE reservation.account_id = p_account_id
        AND reservation.vault_id = p_vault_id
        AND reservation.reservation_id = p_reservation_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'hosted_reservation_invalid'; END IF;
  END IF;
  RETURN QUERY SELECT v_allowed, v_base;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.reserve_upload_with_base_current(
  uuid, uuid, uuid, bigint, timestamptz, bigint
) FROM PUBLIC;
