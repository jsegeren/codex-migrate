-- Disposable database after migration 0035. Administrator email proof may
-- approve only bounded seats, with an immutable attribution record. It grants
-- no Vault, device, entitlement, or recovery capability.
BEGIN;
INSERT INTO hosted.accounts (account_id, allowance_bytes, owner_kind) VALUES
  ('55555555-5555-4555-8555-555555555551', 0, 'business');
INSERT INTO hosted.business_accounts
  (account_id, organization_name, approval_reference,
   purchaser_contact_email, admin_contact_email) VALUES
  ('55555555-5555-4555-8555-555555555551', 'Seat Test',
   '55555555-5555-4555-8555-555555555552',
   'buyer@example.test', 'admin@example.test');
INSERT INTO hosted.business_admin_sessions
  (token_hash, account_id, expires_at) VALUES
  (repeat('a', 64), '55555555-5555-4555-8555-555555555551',
   clock_timestamp() + interval '1 hour');

DO $$
DECLARE v_seat uuid;
BEGIN
  v_seat := hosted.approve_business_seat(repeat('a', 64),
    '55555555-5555-4555-8555-555555555553', 'worker@example.test',
    '55555555-5555-4555-8555-555555555554',
    '55555555-5555-4555-8555-555555555555');
  IF v_seat IS NOT NULL THEN RAISE EXCEPTION 'zero-limit seat approved'; END IF;
  IF EXISTS (SELECT 1 FROM hosted.business_admin_actions) THEN
    RAISE EXCEPTION 'zero-limit approval wrote audit'; END IF;
END;
$$;
UPDATE hosted.business_accounts SET pilot_seat_limit = 1
  WHERE account_id = '55555555-5555-4555-8555-555555555551';

DO $$
DECLARE v_seat uuid;
BEGIN
  v_seat := hosted.approve_business_seat(repeat('a', 64),
    '55555555-5555-4555-8555-555555555553', 'worker@example.test',
    '55555555-5555-4555-8555-555555555554',
    '55555555-5555-4555-8555-555555555555');
  IF v_seat IS DISTINCT FROM '55555555-5555-4555-8555-555555555553'::uuid THEN
    RAISE EXCEPTION 'approved seat missing'; END IF;
  -- Lost response: same decision, no second action.
  v_seat := hosted.approve_business_seat(repeat('a', 64),
    '55555555-5555-4555-8555-555555555553', 'worker@example.test',
    '55555555-5555-4555-8555-555555555554',
    '55555555-5555-4555-8555-555555555556');
  IF v_seat IS NULL OR
     (SELECT count(*) FROM hosted.business_admin_actions) != 1 THEN
    RAISE EXCEPTION 'seat retry was not idempotent'; END IF;
  IF (SELECT admin_contact_at_action FROM hosted.business_admin_actions) !=
     'admin@example.test' THEN RAISE EXCEPTION 'audit lost actor'; END IF;
  BEGIN
    INSERT INTO hosted.business_seats
      (account_id, seat_id, worker_contact_email, approval_reference)
      VALUES ('55555555-5555-4555-8555-555555555551',
        '55555555-5555-4555-8555-555555555557', 'worker@example.test',
        '55555555-5555-4555-8555-555555555558');
    RAISE EXCEPTION 'duplicate active worker seat accepted';
  EXCEPTION WHEN unique_violation THEN NULL;
  END;

  v_seat := hosted.approve_business_seat(repeat('a', 64),
    '55555555-5555-4555-8555-555555555557', 'other@example.test',
    '55555555-5555-4555-8555-555555555558',
    '55555555-5555-4555-8555-555555555559');
  IF v_seat IS NOT NULL THEN RAISE EXCEPTION 'seat ceiling bypassed'; END IF;
  v_seat := hosted.approve_business_seat(repeat('a', 64),
    '55555555-5555-4555-8555-555555555553', 'changed@example.test',
    '55555555-5555-4555-8555-555555555554',
    '55555555-5555-4555-8555-55555555555a');
  IF v_seat IS NOT NULL THEN RAISE EXCEPTION 'seat email changed by retry'; END IF;
  v_seat := hosted.approve_business_seat(repeat('b', 64),
    '55555555-5555-4555-8555-555555555557', 'other@example.test',
    '55555555-5555-4555-8555-555555555558',
    '55555555-5555-4555-8555-55555555555b');
  IF v_seat IS NOT NULL THEN RAISE EXCEPTION 'unknown admin approved seat'; END IF;

  BEGIN
    UPDATE hosted.business_admin_actions SET admin_contact_at_action = 'false'
      WHERE seat_id = '55555555-5555-4555-8555-555555555553';
    RAISE EXCEPTION 'audit could be rewritten';
  EXCEPTION WHEN raise_exception THEN
    IF SQLERRM != 'hosted_business_admin_action_is_immutable' THEN RAISE; END IF;
  END;
  BEGIN
    DELETE FROM hosted.business_admin_actions
      WHERE seat_id = '55555555-5555-4555-8555-555555555553';
    RAISE EXCEPTION 'audit could be deleted';
  EXCEPTION WHEN raise_exception THEN
    IF SQLERRM != 'hosted_business_admin_action_is_immutable' THEN RAISE; END IF;
  END;
  BEGIN
    UPDATE hosted.business_seats SET worker_contact_email = 'other@example.test'
      WHERE seat_id = '55555555-5555-4555-8555-555555555553';
    RAISE EXCEPTION 'approved seat could be reassigned';
  EXCEPTION WHEN raise_exception THEN
    IF SQLERRM != 'hosted_business_seat_identity_is_immutable' THEN RAISE; END IF;
  END;
END;
$$;

UPDATE hosted.business_accounts SET admin_contact_email = 'new@example.test'
  WHERE account_id = '55555555-5555-4555-8555-555555555551';
DO $$
BEGIN
  IF hosted.approve_business_seat(repeat('a', 64),
    '55555555-5555-4555-8555-555555555557', 'other@example.test',
    '55555555-5555-4555-8555-555555555558',
    '55555555-5555-4555-8555-55555555555c') IS NOT NULL THEN
    RAISE EXCEPTION 'revoked admin approved seat'; END IF;
END;
$$;
ROLLBACK;
