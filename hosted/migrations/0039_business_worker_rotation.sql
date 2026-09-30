-- Scheduled business backup must not stop merely because its first device
-- bearer reaches the 29-day limit. Rotate the exact active worker bearer in
-- one transaction; recovery-only sessions can never become upload workers.
CREATE FUNCTION hosted.rotate_business_worker_device(
  p_old_hash text, p_old_device_id uuid,
  p_new_hash text, p_new_device_id uuid
) RETURNS TABLE(account_id uuid, seat_id uuid, vault_id uuid)
LANGUAGE plpgsql AS $$
DECLARE
  v_old hosted.business_device_sessions%ROWTYPE;
  v_account uuid;
  v_seat uuid;
  v_now timestamptz;
BEGIN
  IF p_old_hash IS NULL OR p_old_hash !~ '^[0-9a-f]{64}$' OR
     p_new_hash IS NULL OR p_new_hash !~ '^[0-9a-f]{64}$' OR
     p_old_hash = p_new_hash OR p_old_device_id IS NULL OR
     p_new_device_id IS NULL OR p_old_device_id = p_new_device_id THEN
    RETURN;
  END IF;
  SELECT d.account_id, d.seat_id INTO v_account, v_seat
    FROM hosted.business_device_sessions AS d
    WHERE d.token_hash = p_old_hash AND d.device_id = p_old_device_id;
  IF v_account IS NULL OR v_seat IS NULL THEN RETURN; END IF;

  -- Seat-first locking matches revocation. Recheck the token after the lock:
  -- an expired, revoked, recovery-only, or concurrently rotated bearer fails.
  PERFORM 1 FROM hosted.business_seats AS s
    WHERE s.account_id = v_account AND s.seat_id = v_seat
      AND s.revoked_at IS NULL FOR UPDATE;
  IF NOT FOUND THEN RETURN; END IF;
  SELECT d.* INTO v_old FROM hosted.business_device_sessions AS d
    WHERE d.token_hash = p_old_hash AND d.device_id = p_old_device_id
    FOR UPDATE;
  v_now := clock_timestamp();
  IF v_old.token_hash IS NULL OR v_old.account_id <> v_account OR
     v_old.seat_id <> v_seat OR
     v_old.access_purpose <> 'worker' OR v_old.revoked_at IS NOT NULL OR
     v_old.expires_at <= v_now OR
     EXISTS (SELECT 1 FROM hosted.business_device_sessions AS d
       WHERE d.device_id = p_new_device_id) OR
     (SELECT count(*) FROM hosted.business_device_sessions AS d
       WHERE d.account_id = v_old.account_id AND d.seat_id = v_old.seat_id
         AND d.vault_id = v_old.vault_id AND d.access_purpose = 'worker'
         AND d.revoked_at IS NULL AND d.expires_at > v_now) <> 1 THEN
    RETURN;
  END IF;
  UPDATE hosted.business_device_sessions AS d SET revoked_at = v_now
    WHERE d.token_hash = p_old_hash;
  INSERT INTO hosted.business_device_sessions
    (token_hash, account_id, seat_id, vault_id, device_id,
     created_at, expires_at, access_purpose)
    VALUES (p_new_hash, v_old.account_id, v_old.seat_id, v_old.vault_id,
      p_new_device_id, v_now, v_now + interval '29 days', 'worker');
  account_id := v_old.account_id;
  seat_id := v_old.seat_id;
  vault_id := v_old.vault_id;
  RETURN NEXT;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.rotate_business_worker_device(
  text, uuid, text, uuid) FROM PUBLIC;
