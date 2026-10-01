-- A check-in is a device-reported observation, not a recovery certificate.
-- The server clock makes a silent/offline Mac detectable without trusting the
-- worker's wall clock. The independently published snapshot stays separate.
CREATE TABLE hosted.business_backup_checks (
  account_id uuid NOT NULL,
  seat_id uuid NOT NULL,
  vault_id uuid NOT NULL,
  device_id uuid NOT NULL,
  reported_state text NOT NULL CHECK (reported_state IN
    ('verified', 'unchanged', 'needs_attention', 'failed')),
  reported_snapshot_id uuid,
  checked_at timestamptz NOT NULL,
  PRIMARY KEY (account_id, vault_id),
  FOREIGN KEY (account_id, seat_id, vault_id)
    REFERENCES hosted.business_seat_vaults (account_id, seat_id, vault_id),
  CHECK ((reported_state = 'failed') = (reported_snapshot_id IS NULL))
);
--> statement-breakpoint
CREATE FUNCTION hosted.record_business_backup_check(
  p_token_hash text, p_device_id uuid, p_state text, p_snapshot_id uuid
) RETURNS TABLE(account_id uuid, seat_id uuid, vault_id uuid,
  checked_at timestamptz)
LANGUAGE plpgsql AS $$
DECLARE
  v_account uuid;
  v_seat uuid;
  v_device hosted.business_device_sessions%ROWTYPE;
  v_latest uuid;
  v_coverage text;
  v_now timestamptz;
BEGIN
  IF p_token_hash IS NULL OR p_token_hash !~ '^[0-9a-f]{64}$' OR
     p_device_id IS NULL OR p_state IS NULL OR p_state NOT IN
       ('verified', 'unchanged', 'needs_attention', 'failed') OR
     (p_state = 'failed') <> (p_snapshot_id IS NULL) THEN
    RETURN;
  END IF;
  SELECT d.account_id, d.seat_id INTO v_account, v_seat
    FROM hosted.business_device_sessions AS d
    WHERE d.token_hash = p_token_hash AND d.device_id = p_device_id;
  IF v_account IS NULL OR v_seat IS NULL THEN RETURN; END IF;

  -- Seat-first locking matches revocation and worker rotation. Recheck the
  -- bearer after the lock so a revoked/expired/recovery-only device fails.
  PERFORM 1 FROM hosted.business_seats AS s
    WHERE s.account_id = v_account AND s.seat_id = v_seat
      AND s.revoked_at IS NULL FOR SHARE;
  IF NOT FOUND THEN RETURN; END IF;
  SELECT d.* INTO v_device FROM hosted.business_device_sessions AS d
    WHERE d.token_hash = p_token_hash AND d.device_id = p_device_id;
  v_now := clock_timestamp();
  IF v_device.token_hash IS NULL OR v_device.account_id <> v_account OR
     v_device.seat_id <> v_seat OR
     v_device.access_purpose <> 'worker' OR
     v_device.revoked_at IS NOT NULL OR v_device.expires_at <= v_now THEN
    RETURN;
  END IF;
  IF p_state <> 'failed' THEN
    SELECT v.last_good_snapshot_id, latest.source_coverage
      INTO v_latest, v_coverage FROM hosted.vaults AS v
      LEFT JOIN hosted.snapshots AS latest
        ON latest.account_id = v.account_id AND
          latest.vault_id = v.vault_id AND
          latest.snapshot_id = v.last_good_snapshot_id
      WHERE v.account_id = v_device.account_id AND
        v.vault_id = v_device.vault_id;
    IF v_latest IS NULL OR v_latest <> p_snapshot_id OR
       (p_state IN ('verified', 'unchanged') AND
         v_coverage <> 'complete') THEN RETURN; END IF;
  END IF;

  INSERT INTO hosted.business_backup_checks AS c
    (account_id, seat_id, vault_id, device_id, reported_state,
     reported_snapshot_id, checked_at)
    VALUES (v_device.account_id, v_device.seat_id, v_device.vault_id,
      p_device_id, p_state, p_snapshot_id, v_now)
    ON CONFLICT ON CONSTRAINT business_backup_checks_pkey DO UPDATE SET
      device_id = EXCLUDED.device_id,
      reported_state = EXCLUDED.reported_state,
      reported_snapshot_id = EXCLUDED.reported_snapshot_id,
      checked_at = EXCLUDED.checked_at;
  account_id := v_device.account_id;
  seat_id := v_device.seat_id;
  vault_id := v_device.vault_id;
  checked_at := v_now;
  RETURN NEXT;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.record_business_backup_check(
  text, uuid, text, uuid) FROM PUBLIC;
