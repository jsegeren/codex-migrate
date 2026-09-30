-- Disposable database after migration 0040. Check-ins are authorized against
-- the exact current worker and independently published snapshot pointer.
BEGIN;
INSERT INTO hosted.accounts (account_id, allowance_bytes, owner_kind) VALUES
  ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1', 1, 'business');
INSERT INTO hosted.business_accounts
  (account_id, organization_name, approval_reference,
   purchaser_contact_email, admin_contact_email) VALUES
  ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1', 'Health Test',
   'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2',
   'buyer@example.test', 'admin@example.test');
INSERT INTO hosted.business_seats
  (account_id, seat_id, worker_contact_email, approval_reference) VALUES
  ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1',
   'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3', 'worker@example.test',
   'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa4');
INSERT INTO hosted.vaults (account_id, vault_id) VALUES
  ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1',
   'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa5');
INSERT INTO hosted.business_seat_vaults (account_id, seat_id, vault_id) VALUES
  ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1',
   'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3',
   'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa5');
INSERT INTO hosted.business_device_sessions
  (token_hash, account_id, seat_id, vault_id, device_id,
   expires_at, access_purpose) VALUES
  (repeat('a', 64), 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1',
   'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3',
   'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa5',
   'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa6',
   clock_timestamp() + interval '1 day', 'worker'),
  (repeat('b', 64), 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1',
   'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3',
   'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa5',
   'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa7',
   clock_timestamp() + interval '1 hour', 'recovery');
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM hosted.record_business_backup_check(
      repeat('b', 64), 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa7',
      'failed', NULL)) OR
     EXISTS (SELECT 1 FROM hosted.record_business_backup_check(
      repeat('a', 64), 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa7',
      'failed', NULL)) OR
     EXISTS (SELECT 1 FROM hosted.record_business_backup_check(
      repeat('a', 64), 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa6',
      'verified', 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa9')) THEN
    RAISE EXCEPTION 'invalid device or unowned snapshot checked in'; END IF;
  IF (SELECT count(*) FROM hosted.record_business_backup_check(
      repeat('a', 64), 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa6',
      'failed', NULL)) != 1 THEN
    RAISE EXCEPTION 'active worker could not report a failure'; END IF;
  IF (SELECT reported_state FROM hosted.business_backup_checks
      WHERE account_id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1') <> 'failed' THEN
    RAISE EXCEPTION 'failure check was not stored'; END IF;
END;
$$;
INSERT INTO hosted.upload_reservations
  (reservation_id, account_id, vault_id, reserved_bytes, expires_at,
   state) VALUES
  ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa8',
   'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1',
   'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa5', 1,
   clock_timestamp() + interval '1 hour', 'published');
INSERT INTO hosted.snapshots
  (account_id, vault_id, snapshot_id, reservation_id,
   verified_object_count, source_coverage) VALUES
  ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1',
   'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa5',
   'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa9',
   'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa8', 3, 'complete');
UPDATE hosted.vaults
  SET last_good_snapshot_id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa9'
  WHERE account_id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1';
DO $$
BEGIN
  IF (SELECT count(*) FROM hosted.record_business_backup_check(
      repeat('a', 64), 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa6',
      'verified', 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa9')) != 1 OR
     (SELECT count(*) FROM hosted.record_business_backup_check(
      repeat('a', 64), 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa6',
      'unchanged', 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa9')) != 1 THEN
    RAISE EXCEPTION 'verified published pointer could not be checked'; END IF;
  IF (SELECT reported_state FROM hosted.business_backup_checks
      WHERE account_id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1') <> 'unchanged' OR
     (SELECT count(*) FROM hosted.business_backup_checks
      WHERE account_id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1') != 1 THEN
    RAISE EXCEPTION 'latest check not recorded once'; END IF;
END;
$$;
UPDATE hosted.snapshots SET source_coverage = 'needs_attention'
  WHERE account_id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1';
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM hosted.record_business_backup_check(
      repeat('a', 64), 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa6',
      'verified', 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa9')) OR
     (SELECT count(*) FROM hosted.record_business_backup_check(
      repeat('a', 64), 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa6',
      'needs_attention', 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa9')) != 1 THEN
    RAISE EXCEPTION 'at-risk source was falsely checked as verified'; END IF;
END;
$$;
UPDATE hosted.business_seats SET revoked_at = clock_timestamp()
  WHERE account_id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1';
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM hosted.record_business_backup_check(
      repeat('a', 64), 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa6',
      'failed', NULL)) THEN
    RAISE EXCEPTION 'revoked seat checked in'; END IF;
END;
$$;
ROLLBACK;
