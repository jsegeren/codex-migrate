-- A client may durably record its random reservation ID before contacting the
-- service. Retrying that exact ID after a lost response returns the original
-- base and expiry without reserving another byte. Fresh device, purchase and
-- subscription checks still precede this server-only function on every call.
CREATE FUNCTION hosted.reserve_upload_idempotent_current(
  p_account_id uuid,
  p_vault_id uuid,
  p_reservation_id uuid,
  p_bytes bigint,
  p_expires_at timestamptz,
  p_current_allowance bigint
) RETURNS TABLE (allowed boolean, base_snapshot_id uuid, expires_at timestamptz)
  LANGUAGE plpgsql AS $$
DECLARE
  v_existing hosted.upload_reservations%ROWTYPE;
  v_allowed boolean;
BEGIN
  IF p_reservation_id IS NULL OR p_bytes IS NULL OR p_bytes <= 0 OR
     p_expires_at IS NULL OR p_expires_at <= clock_timestamp() OR
     p_expires_at > clock_timestamp() + interval '1 hour' OR
     p_current_allowance IS NULL OR p_current_allowance <= 0 THEN
    RETURN QUERY SELECT false, NULL::uuid, NULL::timestamptz;
    RETURN;
  END IF;

  -- The account lock serializes a retry against concurrent reservation and
  -- publication, even when the same ID has not been inserted yet.
  PERFORM 1 FROM hosted.accounts AS account
    WHERE account.account_id = p_account_id FOR UPDATE;
  IF NOT FOUND THEN
    RETURN QUERY SELECT false, NULL::uuid, NULL::timestamptz;
    RETURN;
  END IF;
  SELECT * INTO v_existing FROM hosted.upload_reservations AS reservation
    WHERE reservation.reservation_id = p_reservation_id;
  IF FOUND THEN
    IF v_existing.account_id = p_account_id AND
       v_existing.vault_id = p_vault_id AND
       v_existing.state = 'active' AND
       v_existing.expires_at > clock_timestamp() AND
       v_existing.reserved_bytes >= p_bytes THEN
      RETURN QUERY SELECT true, v_existing.base_snapshot_id,
                          v_existing.expires_at;
    ELSE
      RETURN QUERY SELECT false, NULL::uuid, NULL::timestamptz;
    END IF;
    RETURN;
  END IF;

  v_allowed := hosted.reserve_upload_current(p_account_id, p_vault_id,
    p_reservation_id, p_bytes, p_expires_at, p_current_allowance);
  IF NOT v_allowed THEN
    RETURN QUERY SELECT false, NULL::uuid, NULL::timestamptz;
    RETURN;
  END IF;
  SELECT * INTO v_existing FROM hosted.upload_reservations AS reservation
    WHERE reservation.account_id = p_account_id AND
          reservation.vault_id = p_vault_id AND
          reservation.reservation_id = p_reservation_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'hosted_reservation_invalid'; END IF;
  RETURN QUERY SELECT true, v_existing.base_snapshot_id, v_existing.expires_at;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.reserve_upload_idempotent_current(
  uuid, uuid, uuid, bigint, timestamptz, bigint
) FROM PUBLIC;
