-- Disposable database after migration 0039. An active worker, not a
-- recovery-only device, may replace its expiring bearer once.
BEGIN;
INSERT INTO hosted.accounts (account_id, allowance_bytes, owner_kind)
  VALUES ('99999999-9999-4999-8999-999999999991', 0, 'business');
INSERT INTO hosted.business_accounts
  (account_id, organization_name, approval_reference,
   purchaser_contact_email, admin_contact_email) VALUES
  ('99999999-9999-4999-8999-999999999991', 'Rotation Test',
   '99999999-9999-4999-8999-999999999992',
   'buyer@example.test', 'admin@example.test');
INSERT INTO hosted.business_seats
  (account_id, seat_id, worker_contact_email, approval_reference) VALUES
  ('99999999-9999-4999-8999-999999999991',
   '99999999-9999-4999-8999-999999999993', 'worker@example.test',
   '99999999-9999-4999-8999-999999999994');
INSERT INTO hosted.vaults (account_id, vault_id) VALUES
  ('99999999-9999-4999-8999-999999999991',
   '99999999-9999-4999-8999-999999999995');
INSERT INTO hosted.business_seat_vaults (account_id, seat_id, vault_id) VALUES
  ('99999999-9999-4999-8999-999999999991',
   '99999999-9999-4999-8999-999999999993',
   '99999999-9999-4999-8999-999999999995');
INSERT INTO hosted.business_device_sessions
  (token_hash, account_id, seat_id, vault_id, device_id, expires_at) VALUES
  (repeat('1', 64), '99999999-9999-4999-8999-999999999991',
   '99999999-9999-4999-8999-999999999993',
   '99999999-9999-4999-8999-999999999995',
   '99999999-9999-4999-8999-999999999996',
   clock_timestamp() + interval '1 day');
INSERT INTO hosted.business_device_sessions
  (token_hash, account_id, seat_id, vault_id, device_id,
   expires_at, access_purpose) VALUES
  (repeat('3', 64), '99999999-9999-4999-8999-999999999991',
   '99999999-9999-4999-8999-999999999993',
   '99999999-9999-4999-8999-999999999995',
   '99999999-9999-4999-8999-999999999997',
   clock_timestamp() + interval '1 hour', 'recovery');

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM hosted.rotate_business_worker_device(
      repeat('3', 64), '99999999-9999-4999-8999-999999999997',
      repeat('4', 64), '99999999-9999-4999-8999-999999999998')) THEN
    RAISE EXCEPTION 'recovery-only bearer became worker'; END IF;
  IF EXISTS (SELECT 1 FROM hosted.rotate_business_worker_device(
      repeat('1', 64), '99999999-9999-4999-8999-999999999997',
      repeat('2', 64), '99999999-9999-4999-8999-999999999998')) THEN
    RAISE EXCEPTION 'wrong old device rotated'; END IF;
  IF (SELECT count(*) FROM hosted.rotate_business_worker_device(
      repeat('1', 64), '99999999-9999-4999-8999-999999999996',
      repeat('2', 64), '99999999-9999-4999-8999-999999999998')) != 1 THEN
    RAISE EXCEPTION 'worker bearer did not rotate'; END IF;
  IF EXISTS (SELECT 1 FROM hosted.rotate_business_worker_device(
      repeat('1', 64), '99999999-9999-4999-8999-999999999996',
      repeat('5', 64), '99999999-9999-4999-8999-999999999999')) THEN
    RAISE EXCEPTION 'revoked old bearer rotated twice'; END IF;
  IF NOT EXISTS (SELECT 1 FROM hosted.business_device_sessions
      WHERE token_hash = repeat('1', 64) AND revoked_at IS NOT NULL) OR
     NOT EXISTS (SELECT 1 FROM hosted.business_device_sessions
      WHERE token_hash = repeat('2', 64) AND access_purpose = 'worker'
        AND revoked_at IS NULL AND
        expires_at = created_at + interval '29 days') THEN
    RAISE EXCEPTION 'rotation did not atomically replace worker'; END IF;
  IF (SELECT count(*) FROM hosted.business_device_sessions
      WHERE account_id = '99999999-9999-4999-8999-999999999991'
        AND seat_id = '99999999-9999-4999-8999-999999999993'
        AND access_purpose = 'worker' AND revoked_at IS NULL
        AND expires_at > clock_timestamp()) != 1 THEN
    RAISE EXCEPTION 'multiple active worker bearers'; END IF;
END;
$$;
UPDATE hosted.business_seats SET revoked_at = clock_timestamp()
  WHERE account_id = '99999999-9999-4999-8999-999999999991'
    AND seat_id = '99999999-9999-4999-8999-999999999993';
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM hosted.rotate_business_worker_device(
      repeat('2', 64), '99999999-9999-4999-8999-999999999998',
      repeat('6', 64), '99999999-9999-4999-8999-999999999999')) THEN
    RAISE EXCEPTION 'revoked seat rotated worker'; END IF;
END;
$$;
ROLLBACK;
