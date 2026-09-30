-- Disposable PostgreSQL database after migration 0041. One alert per active
-- seat/Vault incident; a claimed or uncertain delivery is never auto-retried.
BEGIN;
INSERT INTO hosted.accounts (account_id, allowance_bytes, owner_kind) VALUES
  ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1', 1, 'business');
INSERT INTO hosted.business_accounts
  (account_id, organization_name, approval_reference,
   purchaser_contact_email, admin_contact_email) VALUES
  ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1', 'Alert Test',
   'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2',
   'buyer@example.test', 'admin@example.test');
INSERT INTO hosted.business_seats
  (account_id, seat_id, worker_contact_email, approval_reference) VALUES
  ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1',
   'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb3', 'worker@example.test',
   'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb4');
DO $$
DECLARE v_claimed integer;
BEGIN
  SELECT count(*) INTO v_claimed FROM hosted.claim_business_backup_alerts();
  IF v_claimed != 1 OR
     (SELECT reason FROM hosted.business_backup_alerts
       WHERE account_id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1') <>
       'not_enrolled' OR
     EXISTS (SELECT 1 FROM hosted.claim_business_backup_alerts()) THEN
    RAISE EXCEPTION 'unassigned seat alert was not claimed exactly once';
  END IF;
  IF hosted.record_business_backup_alert_delivery(
      (SELECT alert_id FROM hosted.business_backup_alerts
        WHERE account_id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1'),
      'invalid') OR
     NOT hosted.record_business_backup_alert_delivery(
      (SELECT alert_id FROM hosted.business_backup_alerts
        WHERE account_id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1'),
      'uncertain') OR
     hosted.record_business_backup_alert_delivery(
      (SELECT alert_id FROM hosted.business_backup_alerts
        WHERE account_id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1'),
      'accepted') THEN
    RAISE EXCEPTION 'uncertain delivery was retried or rewritten';
  END IF;
END;
$$;
INSERT INTO hosted.vaults (account_id, vault_id) VALUES
  ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1',
   'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb5');
INSERT INTO hosted.business_seat_vaults (account_id, seat_id, vault_id) VALUES
  ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1',
   'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb3',
   'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb5');
DO $$
DECLARE v_claimed integer;
BEGIN
  SELECT count(*) INTO v_claimed FROM hosted.claim_business_backup_alerts();
  IF v_claimed != 1 OR
     (SELECT count(*) FROM hosted.business_backup_alerts
       WHERE account_id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1'
         AND resolved_at IS NOT NULL) != 1 OR
     (SELECT reason FROM hosted.business_backup_alerts
       WHERE account_id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1'
         AND resolved_at IS NULL) <> 'no_published_backup' THEN
    RAISE EXCEPTION 'seat assignment did not resolve prior incident';
  END IF;
END;
$$;
INSERT INTO hosted.upload_reservations
  (reservation_id, account_id, vault_id, reserved_bytes, expires_at,
   state) VALUES
  ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb6',
   'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1',
   'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb5', 1,
   clock_timestamp() + interval '1 hour', 'published');
INSERT INTO hosted.snapshots
  (account_id, vault_id, snapshot_id, reservation_id,
   verified_object_count, source_coverage) VALUES
  ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1',
   'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb5',
   'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb7',
   'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb6', 3, 'complete');
UPDATE hosted.vaults
  SET last_good_snapshot_id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb7'
  WHERE account_id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1';
INSERT INTO hosted.business_backup_checks
  (account_id, seat_id, vault_id, device_id, reported_state,
   reported_snapshot_id, checked_at) VALUES
  ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1',
   'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb3',
   'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb5',
   'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb8', 'verified',
   'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb7', clock_timestamp());
DO $$
BEGIN
  PERFORM * FROM hosted.claim_business_backup_alerts();
  IF EXISTS (SELECT 1 FROM hosted.business_backup_alerts
       WHERE account_id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1'
         AND delivery_state = 'claimed' AND resolved_at IS NULL) OR
     EXISTS (SELECT 1 FROM hosted.business_backup_alerts
       WHERE account_id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1'
         AND resolved_at IS NULL) THEN
    RAISE EXCEPTION 'healthy seat retained an open incident';
  END IF;
END;
$$;
UPDATE hosted.business_backup_checks
  SET checked_at = clock_timestamp() - interval '2 hours'
  WHERE account_id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1';
DO $$
DECLARE v_claimed integer;
BEGIN
  SELECT count(*) INTO v_claimed FROM hosted.claim_business_backup_alerts();
  IF v_claimed != 1 OR
     (SELECT reason FROM hosted.business_backup_alerts
       WHERE account_id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1'
         AND resolved_at IS NULL) <> 'overdue' OR
     EXISTS (SELECT 1 FROM hosted.claim_business_backup_alerts()) THEN
    RAISE EXCEPTION 'offline Mac did not open one overdue alert';
  END IF;
END;
$$;
UPDATE hosted.business_backup_checks SET checked_at = clock_timestamp()
  WHERE account_id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1';
DO $$
BEGIN
  PERFORM * FROM hosted.claim_business_backup_alerts();
  IF EXISTS (SELECT 1 FROM hosted.business_backup_alerts
      WHERE account_id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1'
        AND resolved_at IS NULL) THEN
    RAISE EXCEPTION 'fresh check did not resolve overdue alert';
  END IF;
END;
$$;
UPDATE hosted.business_backup_checks SET reported_state = 'failed',
  reported_snapshot_id = NULL
  WHERE account_id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1';
DO $$
DECLARE v_claimed integer;
BEGIN
  SELECT count(*) INTO v_claimed FROM hosted.claim_business_backup_alerts();
  IF v_claimed != 1 OR
     (SELECT reason FROM hosted.business_backup_alerts
       WHERE account_id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1'
         AND resolved_at IS NULL) <> 'failed_run' THEN
    RAISE EXCEPTION 'new failure did not open a fresh incident';
  END IF;
END;
$$;
UPDATE hosted.business_seats SET revoked_at = clock_timestamp()
  WHERE account_id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1';
DO $$
BEGIN
  PERFORM * FROM hosted.claim_business_backup_alerts();
  IF EXISTS (SELECT 1 FROM hosted.business_backup_alerts
       WHERE account_id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1'
         AND delivery_state = 'claimed' AND resolved_at IS NULL) OR
     EXISTS (SELECT 1 FROM hosted.business_backup_alerts
       WHERE account_id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1'
         AND resolved_at IS NULL) THEN
    RAISE EXCEPTION 'revoked seat still generates alerts';
  END IF;
END;
$$;
ROLLBACK;
