-- Disposable database after migration 0036. Worker email proof pairs exactly
-- one first device under an approved seat and grants no storage allowance.
BEGIN;
INSERT INTO hosted.accounts (account_id, allowance_bytes, owner_kind) VALUES
  ('66666666-6666-4666-8666-666666666661', 0, 'business');
INSERT INTO hosted.business_accounts
  (account_id, organization_name, approval_reference,
   purchaser_contact_email, admin_contact_email, pilot_seat_limit) VALUES
  ('66666666-6666-4666-8666-666666666661', 'Pair Test',
   '66666666-6666-4666-8666-666666666662',
   'buyer@example.test', 'admin@example.test', 1);
INSERT INTO hosted.business_seats
  (account_id, seat_id, worker_contact_email, approval_reference) VALUES
  ('66666666-6666-4666-8666-666666666661',
   '66666666-6666-4666-8666-666666666663', 'worker@example.test',
   '66666666-6666-4666-8666-666666666664');
INSERT INTO hosted.business_admin_sessions
  (token_hash, account_id, expires_at) VALUES
  (repeat('f', 64), '66666666-6666-4666-8666-666666666661',
   clock_timestamp() + interval '1 hour');

DO $$
DECLARE v_contact text;
BEGIN
  v_contact := hosted.issue_business_worker_challenge(
    repeat('f', 64),
    '66666666-6666-4666-8666-666666666661',
    '66666666-6666-4666-8666-666666666663', repeat('a', 64));
  IF v_contact IS DISTINCT FROM 'worker@example.test' THEN
    RAISE EXCEPTION 'worker challenge escaped approved seat'; END IF;
  IF hosted.issue_business_worker_challenge(
    repeat('f', 64),
    '66666666-6666-4666-8666-666666666661',
    '66666666-6666-4666-8666-666666666663', repeat('b', 64)) IS NOT NULL THEN
    RAISE EXCEPTION 'challenge cooldown bypassed'; END IF;
  IF hosted.issue_business_worker_challenge(
    repeat('f', 64),
    '66666666-6666-4666-8666-666666666665',
    '66666666-6666-4666-8666-666666666663', repeat('b', 64)) IS NOT NULL THEN
    RAISE EXCEPTION 'cross-account challenge issued'; END IF;
  IF hosted.claim_business_first_device(
    '66666666-6666-4666-8666-666666666661',
    '66666666-6666-4666-8666-666666666663', repeat('a', 64),
    '66666666-6666-4666-8666-666666666666',
    '66666666-6666-4666-8666-666666666667', repeat('c', 64)) IS NOT NULL THEN
    RAISE EXCEPTION 'undelivered challenge paired device'; END IF;
  IF NOT hosted.record_business_worker_challenge_delivery(
    repeat('a', 64), 'sent') THEN
    RAISE EXCEPTION 'delivery state missing'; END IF;
  IF hosted.record_business_worker_challenge_delivery(
    repeat('a', 64), 'sent') THEN
    RAISE EXCEPTION 'delivery status replay accepted'; END IF;
  IF hosted.claim_business_first_device(
    '66666666-6666-4666-8666-666666666665',
    '66666666-6666-4666-8666-666666666663', repeat('a', 64),
    '66666666-6666-4666-8666-666666666666',
    '66666666-6666-4666-8666-666666666667', repeat('c', 64)) IS NOT NULL THEN
    RAISE EXCEPTION 'cross-account device claim'; END IF;
  IF hosted.claim_business_first_device(
    '66666666-6666-4666-8666-666666666661',
    '66666666-6666-4666-8666-666666666663', repeat('b', 64),
    '66666666-6666-4666-8666-666666666666',
    '66666666-6666-4666-8666-666666666667', repeat('c', 64)) IS NOT NULL THEN
    RAISE EXCEPTION 'wrong worker code paired device'; END IF;
  IF hosted.claim_business_first_device(
    '66666666-6666-4666-8666-666666666661',
    '66666666-6666-4666-8666-666666666663', repeat('a', 64),
    '66666666-6666-4666-8666-666666666666',
    '66666666-6666-4666-8666-666666666667', repeat('c', 64)) IS DISTINCT FROM
    '66666666-6666-4666-8666-666666666666'::uuid THEN
    RAISE EXCEPTION 'approved first device was not paired'; END IF;
  IF (SELECT allowance_bytes FROM hosted.accounts WHERE account_id =
      '66666666-6666-4666-8666-666666666661') != 0 THEN
    RAISE EXCEPTION 'pairing granted storage allowance'; END IF;
  IF (SELECT count(*) FROM hosted.business_device_sessions
      WHERE token_hash = repeat('c', 64)) != 1 THEN
    RAISE EXCEPTION 'business bearer missing'; END IF;
  IF hosted.claim_business_first_device(
    '66666666-6666-4666-8666-666666666661',
    '66666666-6666-4666-8666-666666666663', repeat('a', 64),
    '66666666-6666-4666-8666-666666666668',
    '66666666-6666-4666-8666-666666666669', repeat('d', 64)) IS NOT NULL THEN
    RAISE EXCEPTION 'worker code replay paired second device'; END IF;
  IF hosted.issue_business_worker_challenge(
    repeat('f', 64),
    '66666666-6666-4666-8666-666666666661',
    '66666666-6666-4666-8666-666666666663', repeat('e', 64)) IS NOT NULL THEN
    RAISE EXCEPTION 'paired seat issued new first-device challenge'; END IF;
END;
$$;
UPDATE hosted.business_seats SET revoked_at = clock_timestamp()
  WHERE account_id = '66666666-6666-4666-8666-666666666661'
    AND seat_id = '66666666-6666-4666-8666-666666666663';
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM hosted.business_device_sessions
      WHERE token_hash = repeat('c', 64) AND revoked_at IS NOT NULL) THEN
    RAISE EXCEPTION 'revoked seat retained device access'; END IF;
END;
$$;
INSERT INTO hosted.business_seats
  (account_id, seat_id, worker_contact_email, approval_reference) VALUES
  ('66666666-6666-4666-8666-666666666661',
   '66666666-6666-4666-8666-66666666666a', 'second@example.test',
   '66666666-6666-4666-8666-66666666666b');
INSERT INTO hosted.business_admin_sessions
  (token_hash, account_id, expires_at) VALUES
  (repeat('e', 64), '66666666-6666-4666-8666-666666666661',
   clock_timestamp() + interval '1 hour');
DO $$
BEGIN
  IF hosted.issue_business_worker_challenge(repeat('e', 64),
    '66666666-6666-4666-8666-666666666661',
    '66666666-6666-4666-8666-66666666666a', repeat('d', 64)) IS DISTINCT FROM
    'second@example.test' THEN RAISE EXCEPTION 'second challenge missing'; END IF;
  IF NOT hosted.record_business_worker_challenge_delivery(
    repeat('d', 64), 'sent') THEN RAISE EXCEPTION 'second mail missing'; END IF;
END;
$$;
UPDATE hosted.business_admin_sessions SET revoked_at = clock_timestamp()
  WHERE token_hash = repeat('e', 64);
DO $$
BEGIN
  IF hosted.claim_business_first_device(
    '66666666-6666-4666-8666-666666666661',
    '66666666-6666-4666-8666-66666666666a', repeat('d', 64),
    '66666666-6666-4666-8666-66666666666c',
    '66666666-6666-4666-8666-66666666666d', repeat('9', 64)) IS NOT NULL THEN
    RAISE EXCEPTION 'revoked admin challenge paired device'; END IF;
END;
$$;
ROLLBACK;
