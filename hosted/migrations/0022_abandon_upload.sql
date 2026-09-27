-- A device may stop retrying its own upload without waiting for lease expiry.
-- This is quarantine, not deletion or quota release: issued storage grants may
-- still be replayable. The existing operator cleanup must wait out that window
-- and prove each orphan object's absence before releasing reserved capacity.
CREATE FUNCTION hosted.abandon_upload_reservation(
  p_account_id uuid, p_vault_id uuid, p_reservation_id uuid
) RETURNS boolean LANGUAGE plpgsql AS $$
DECLARE
  v_reservation hosted.upload_reservations%ROWTYPE;
BEGIN
  IF p_account_id IS NULL OR p_vault_id IS NULL OR
     p_reservation_id IS NULL THEN RETURN false; END IF;
  -- Match grant, renewal, publication, and cleanup lock order. A previously
  -- published reservation must never be converted into an orphan.
  PERFORM 1 FROM hosted.accounts WHERE account_id = p_account_id FOR UPDATE;
  IF NOT FOUND THEN RETURN false; END IF;
  SELECT * INTO v_reservation FROM hosted.upload_reservations
    WHERE reservation_id = p_reservation_id AND account_id = p_account_id
      AND vault_id = p_vault_id FOR UPDATE;
  IF NOT FOUND OR v_reservation.state NOT IN ('active', 'cleanup_pending') THEN
    RETURN false;
  END IF;
  IF v_reservation.state = 'active' THEN
    UPDATE hosted.upload_reservations
      SET state = 'cleanup_pending',
          expires_at = least(expires_at, clock_timestamp())
      WHERE reservation_id = p_reservation_id;
  END IF;
  RETURN true;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.abandon_upload_reservation(
  uuid, uuid, uuid
) FROM PUBLIC;
