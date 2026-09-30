-- Disposable PostgreSQL after migration 0034. A manually approved business
-- account's exact admin contact can obtain only a short-lived metadata session.
BEGIN;
INSERT INTO hosted.accounts (account_id, allowance_bytes, owner_kind) VALUES
  ('34343434-3434-4434-8434-343434343431', 0, 'business'),
  ('34343434-3434-4434-8434-343434343432', 0, 'business'),
  ('34343434-3434-4434-8434-343434343433', 0, 'individual');
INSERT INTO hosted.business_accounts
  (account_id, organization_name, approval_reference,
   purchaser_contact_email, admin_contact_email) VALUES
  ('34343434-3434-4434-8434-343434343431', 'One Studio',
    '34343434-3434-4434-8434-343434343434',
    'buyer@shared.example', 'one@shared.example'),
  ('34343434-3434-4434-8434-343434343432', 'Two Studio',
    '34343434-3434-4434-8434-343434343435',
    'buyer@shared.example', 'two@shared.example');

DO $$
DECLARE
  v_contact text;
  v_claimed uuid;
BEGIN
  SELECT hosted.issue_business_admin_challenge(
    '34343434-3434-4434-8434-343434343433', repeat('a', 64))
    INTO v_contact;
  IF v_contact IS NOT NULL THEN
    RAISE EXCEPTION 'individual account issued business admin challenge';
  END IF;

  SELECT hosted.issue_business_admin_challenge(
    '34343434-3434-4434-8434-343434343431', repeat('b', 64))
    INTO v_contact;
  IF v_contact != 'one@shared.example' THEN
    RAISE EXCEPTION 'challenge used another company contact';
  END IF;
  IF hosted.record_business_admin_challenge_delivery(repeat('b', 64), 'sent')
      IS DISTINCT FROM true THEN
    RAISE EXCEPTION 'admin mail acceptance was not recorded';
  END IF;

  SELECT hosted.claim_business_admin_session(
    '34343434-3434-4434-8434-343434343432',
    repeat('b', 64), repeat('c', 64)) INTO v_claimed;
  IF v_claimed IS NOT NULL THEN
    RAISE EXCEPTION 'shared email domain crossed organization boundary';
  END IF;
  SELECT hosted.claim_business_admin_session(
    '34343434-3434-4434-8434-343434343431',
    repeat('b', 64), repeat('c', 64)) INTO v_claimed;
  IF v_claimed != '34343434-3434-4434-8434-343434343431' THEN
    RAISE EXCEPTION 'exact admin challenge did not mint session';
  END IF;
  SELECT hosted.claim_business_admin_session(
    '34343434-3434-4434-8434-343434343431',
    repeat('b', 64), repeat('d', 64)) INTO v_claimed;
  IF v_claimed IS NOT NULL THEN RAISE EXCEPTION 'admin code replayed'; END IF;
  IF NOT EXISTS (
    SELECT 1 FROM hosted.business_admin_sessions
      WHERE token_hash = repeat('c', 64)
        AND account_id = '34343434-3434-4434-8434-343434343431'
        AND expires_at <= created_at + interval '12 hours'
  ) THEN RAISE EXCEPTION 'admin session duration or owner invalid'; END IF;

  SELECT hosted.issue_business_admin_challenge(
    '34343434-3434-4434-8434-343434343431', repeat('e', 64))
    INTO v_contact;
  IF v_contact IS NOT NULL THEN
    RAISE EXCEPTION 'same account received rapid repeat challenge';
  END IF;

  SELECT hosted.issue_business_admin_challenge(
    '34343434-3434-4434-8434-343434343432', repeat('f', 64))
    INTO v_contact;
  IF v_contact != 'two@shared.example' THEN
    RAISE EXCEPTION 'second company did not retain distinct contact';
  END IF;
  IF hosted.record_business_admin_challenge_delivery(repeat('f', 64), 'uncertain')
      IS DISTINCT FROM true THEN
    RAISE EXCEPTION 'uncertain admin mail state was not recorded';
  END IF;
  SELECT hosted.claim_business_admin_session(
    '34343434-3434-4434-8434-343434343432',
    repeat('f', 64), repeat('1', 64)) INTO v_claimed;
  IF v_claimed IS NOT NULL THEN
    RAISE EXCEPTION 'uncertain mail delivery authorized administrator';
  END IF;
END;
$$;

UPDATE hosted.business_accounts SET admin_contact_email = 'replacement@shared.example'
  WHERE account_id = '34343434-3434-4434-8434-343434343431';
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM hosted.business_admin_sessions
      WHERE token_hash = repeat('c', 64) AND revoked_at IS NOT NULL
  ) THEN RAISE EXCEPTION 'admin contact change left session active'; END IF;
  IF NOT EXISTS (
    SELECT 1 FROM hosted.business_admin_challenges
      WHERE account_id = '34343434-3434-4434-8434-343434343431'
        AND consumed_at IS NOT NULL AND mail_state = 'rejected'
  ) THEN RAISE EXCEPTION 'admin contact change left challenge valid'; END IF;

  BEGIN
    UPDATE hosted.business_admin_sessions SET revoked_at = NULL
      WHERE token_hash = repeat('c', 64);
    RAISE EXCEPTION 'revoked admin session was reactivated';
  EXCEPTION WHEN raise_exception THEN
    IF SQLERRM != 'hosted_business_admin_revocation_is_final' THEN RAISE; END IF;
  END;

  BEGIN
    UPDATE hosted.business_accounts
      SET approval_reference = '34343434-3434-4434-8434-343434343436'
      WHERE account_id = '34343434-3434-4434-8434-343434343431';
    RAISE EXCEPTION 'operator approval reference changed in place';
  EXCEPTION WHEN raise_exception THEN
    IF SQLERRM != 'hosted_business_approval_reference_is_immutable' THEN RAISE; END IF;
  END;
END;
$$;
ROLLBACK;
