-- Disposable database after migration 0038. A company-approved request can
-- pair a short-lived read-only replacement without an employee's old Mac.
BEGIN;
INSERT INTO hosted.accounts (account_id, allowance_bytes, owner_kind)
  VALUES ('88888888-8888-4888-8888-888888888881', 0, 'business');
INSERT INTO hosted.business_accounts
  (account_id, organization_name, approval_reference,
   purchaser_contact_email, admin_contact_email) VALUES
  ('88888888-8888-4888-8888-888888888881', 'Recovery Test',
   '88888888-8888-4888-8888-888888888882',
   'buyer@example.test', 'admin@example.test');
INSERT INTO hosted.business_seats
  (account_id, seat_id, worker_contact_email, approval_reference) VALUES
  ('88888888-8888-4888-8888-888888888881',
   '88888888-8888-4888-8888-888888888883', 'worker@example.test',
   '88888888-8888-4888-8888-888888888884');
INSERT INTO hosted.vaults (account_id, vault_id) VALUES
  ('88888888-8888-4888-8888-888888888881',
   '88888888-8888-4888-8888-888888888885');
INSERT INTO hosted.business_seat_vaults (account_id, seat_id, vault_id) VALUES
  ('88888888-8888-4888-8888-888888888881',
   '88888888-8888-4888-8888-888888888883',
   '88888888-8888-4888-8888-888888888885');
INSERT INTO hosted.business_device_sessions
  (token_hash, account_id, seat_id, vault_id, device_id, expires_at) VALUES
  (repeat('1', 64), '88888888-8888-4888-8888-888888888881',
   '88888888-8888-4888-8888-888888888883',
   '88888888-8888-4888-8888-888888888885',
   '88888888-8888-4888-8888-888888888886',
   clock_timestamp() + interval '1 day');
INSERT INTO hosted.business_admin_sessions
  (token_hash, account_id, expires_at) VALUES
  (repeat('a', 64), '88888888-8888-4888-8888-888888888881',
   clock_timestamp() + interval '1 hour');

DO $$
DECLARE v_contact text;
        v_i integer;
BEGIN
  IF hosted.issue_business_recovery_request(repeat('b', 64),
    '88888888-8888-4888-8888-888888888881',
    '88888888-8888-4888-8888-888888888883',
    '88888888-8888-4888-8888-888888888885',
    '88888888-8888-4888-8888-888888888887',
    'Original employee Mac was lost', repeat('c', 64)) IS NOT NULL THEN
    RAISE EXCEPTION 'unverified admin issued recovery'; END IF;
  IF hosted.issue_business_recovery_request(repeat('a', 64),
    '88888888-8888-4888-8888-888888888881',
    '88888888-8888-4888-8888-888888888883',
    '88888888-8888-4888-8888-888888888888',
    '88888888-8888-4888-8888-888888888887',
    'Original employee Mac was lost', repeat('c', 64)) IS NOT NULL THEN
    RAISE EXCEPTION 'wrong Vault issued recovery'; END IF;
  v_contact := hosted.issue_business_recovery_request(repeat('a', 64),
    '88888888-8888-4888-8888-888888888881',
    '88888888-8888-4888-8888-888888888883',
    '88888888-8888-4888-8888-888888888885',
    '88888888-8888-4888-8888-888888888887',
    'Original employee Mac was lost', repeat('c', 64));
  IF v_contact IS DISTINCT FROM 'admin@example.test' THEN
    RAISE EXCEPTION 'recovery code escaped approved admin contact'; END IF;
  IF hosted.claim_business_recovery_device(
    '88888888-8888-4888-8888-888888888881',
    '88888888-8888-4888-8888-888888888883',
    '88888888-8888-4888-8888-888888888885',
    '88888888-8888-4888-8888-888888888887', repeat('c', 64),
    '88888888-8888-4888-8888-888888888889', repeat('d', 64)) IS NOT NULL THEN
    RAISE EXCEPTION 'undelivered recovery code paired device'; END IF;
  IF NOT hosted.record_business_recovery_delivery(repeat('c', 64), 'sent') THEN
    RAISE EXCEPTION 'recovery delivery not recorded'; END IF;
  IF hosted.claim_business_recovery_device(
    '88888888-8888-4888-8888-888888888881',
    '88888888-8888-4888-8888-888888888883',
    '88888888-8888-4888-8888-888888888888',
    '88888888-8888-4888-8888-888888888887', repeat('c', 64),
    '88888888-8888-4888-8888-888888888889', repeat('d', 64)) IS NOT NULL THEN
    RAISE EXCEPTION 'wrong Vault claimed recovery'; END IF;
  IF hosted.claim_business_recovery_device(
    '88888888-8888-4888-8888-888888888881',
    '88888888-8888-4888-8888-888888888883',
    '88888888-8888-4888-8888-888888888885',
    '88888888-8888-4888-8888-888888888887', repeat('c', 64),
    '88888888-8888-4888-8888-888888888889', repeat('d', 64)) IS DISTINCT FROM
    '88888888-8888-4888-8888-888888888885'::uuid THEN
    RAISE EXCEPTION 'company recovery device was not paired'; END IF;
  IF hosted.claim_business_recovery_device(
    '88888888-8888-4888-8888-888888888881',
    '88888888-8888-4888-8888-888888888883',
    '88888888-8888-4888-8888-888888888885',
    '88888888-8888-4888-8888-888888888887', repeat('c', 64),
    '88888888-8888-4888-8888-88888888888a', repeat('e', 64)) IS NOT NULL THEN
    RAISE EXCEPTION 'recovery code replay paired another device'; END IF;
  IF NOT EXISTS (SELECT 1 FROM hosted.business_device_sessions
      WHERE token_hash = repeat('d', 64) AND access_purpose = 'recovery'
        AND expires_at <= created_at + interval '2 hours') THEN
    RAISE EXCEPTION 'replacement device is not short-lived recovery-only'; END IF;
  IF NOT EXISTS (SELECT 1 FROM hosted.business_recovery_audit
      WHERE request_id = '88888888-8888-4888-8888-888888888887'
        AND purpose = 'Original employee Mac was lost') THEN
    RAISE EXCEPTION 'recovery approval audit missing'; END IF;
  FOR v_i IN 2..5 LOOP
    IF hosted.issue_business_recovery_request(repeat('a', 64),
      '88888888-8888-4888-8888-888888888881',
      '88888888-8888-4888-8888-888888888883',
      '88888888-8888-4888-8888-888888888885',
      ('88888888-8888-4888-8888-88888888888' || v_i)::uuid,
      'Recovery rate-limit test', repeat(v_i::text, 64)) IS DISTINCT FROM
      'admin@example.test' THEN
      RAISE EXCEPTION 'valid recovery request was refused'; END IF;
  END LOOP;
  IF hosted.issue_business_recovery_request(repeat('a', 64),
    '88888888-8888-4888-8888-888888888881',
    '88888888-8888-4888-8888-888888888883',
    '88888888-8888-4888-8888-888888888885',
    '88888888-8888-4888-8888-888888888880',
    'Recovery rate-limit test', repeat('6', 64)) IS NOT NULL THEN
    RAISE EXCEPTION 'company recovery request rate limit bypassed'; END IF;
  BEGIN
    DELETE FROM hosted.business_recovery_audit WHERE
      request_id = '88888888-8888-4888-8888-888888888887';
    RAISE EXCEPTION 'recovery audit was deletable';
  EXCEPTION WHEN raise_exception THEN
    IF SQLERRM <> 'hosted_business_recovery_audit_is_immutable' THEN
      RAISE; END IF;
  END;
END;
$$;
UPDATE hosted.business_seats SET revoked_at = clock_timestamp()
  WHERE account_id = '88888888-8888-4888-8888-888888888881'
    AND seat_id = '88888888-8888-4888-8888-888888888883';
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM hosted.business_device_sessions
      WHERE token_hash = repeat('d', 64) AND revoked_at IS NOT NULL) THEN
    RAISE EXCEPTION 'seat revocation left recovery device active'; END IF;
END;
$$;
ROLLBACK;
