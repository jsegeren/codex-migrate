-- Quarantine an expired upload before any provider cleanup. This does not
-- delete ciphertext or release reserved capacity: a later cleanup worker must
-- prove every granted object has a safe disposition first. The extra delay
-- exceeds the lifetime of the last 30-second storage capability plus skew.
CREATE FUNCTION hosted.claim_expired_upload_cleanup(
  p_reservation_id uuid
) RETURNS boolean LANGUAGE plpgsql AS $$
DECLARE
  v_account_id uuid;
  v_reservation hosted.upload_reservations%ROWTYPE;
BEGIN
  IF p_reservation_id IS NULL THEN RETURN false; END IF;

  -- Follow the account-before-reservation lock order used by upload grants,
  -- renewal and publication. Recheck after locking: the first lookup is not
  -- authority and may race a successful renewal or publication.
  SELECT account_id INTO v_account_id FROM hosted.upload_reservations
    WHERE reservation_id = p_reservation_id;
  IF NOT FOUND THEN RETURN false; END IF;
  PERFORM 1 FROM hosted.accounts WHERE account_id = v_account_id FOR UPDATE;
  SELECT * INTO v_reservation FROM hosted.upload_reservations
    WHERE reservation_id = p_reservation_id AND account_id = v_account_id
    FOR UPDATE;
  IF NOT FOUND OR v_reservation.state NOT IN ('active', 'cleanup_pending') OR
     v_reservation.expires_at > clock_timestamp() - interval '2 minutes' THEN
    RETURN false;
  END IF;
  IF v_reservation.state = 'active' THEN
    UPDATE hosted.upload_reservations SET state = 'cleanup_pending'
      WHERE reservation_id = p_reservation_id;
  END IF;
  RETURN true;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.claim_expired_upload_cleanup(uuid)
  FROM PUBLIC;
