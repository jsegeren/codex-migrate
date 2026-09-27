-- A first backup can take longer than one hour. Extend only a still-active
-- reservation after the service rechecks the current paid allowance. Grant
-- and publication paths continue to require their own fresh checks.
CREATE FUNCTION hosted.renew_upload_reservation_current(
  p_account_id uuid,
  p_vault_id uuid,
  p_reservation_id uuid,
  p_new_expires_at timestamptz,
  p_current_allowance bigint
) RETURNS boolean LANGUAGE plpgsql AS $$
DECLARE
  v_retained bigint;
  v_reserved bigint;
BEGIN
  IF p_current_allowance IS NULL OR p_current_allowance <= 0 OR
     p_new_expires_at IS NULL OR
     p_new_expires_at <= clock_timestamp() + interval '2 minutes' OR
     p_new_expires_at > clock_timestamp() + interval '1 hour' OR
     NOT EXISTS (SELECT 1 FROM hosted.upload_reservations
       WHERE reservation_id = p_reservation_id AND account_id = p_account_id
         AND vault_id = p_vault_id) THEN
    RETURN false;
  END IF;

  -- Match the account-before-reservation lock order used by grants and
  -- publication. A downgrade cannot keep an over-limit reservation alive.
  UPDATE hosted.accounts SET allowance_bytes = p_current_allowance
    WHERE account_id = p_account_id
    RETURNING retained_bytes, reserved_bytes INTO v_retained, v_reserved;
  IF NOT FOUND OR v_retained::numeric + v_reserved::numeric >
      p_current_allowance::numeric THEN RETURN false; END IF;

  UPDATE hosted.upload_reservations SET expires_at = p_new_expires_at
    WHERE reservation_id = p_reservation_id AND account_id = p_account_id
      AND vault_id = p_vault_id AND state = 'active'
      AND expires_at > clock_timestamp()
      AND expires_at < p_new_expires_at;
  RETURN FOUND;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.renew_upload_reservation_current(
  uuid, uuid, uuid, timestamptz, bigint
) FROM PUBLIC;
