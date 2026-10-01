-- Disposable PostgreSQL only, after commerce 0000 and hosted 0000-0004.
BEGIN;
INSERT INTO commerce_purchases (session_id, mode, release_id, payment_intent, email)
  VALUES ('cs_test_claim', 'sandbox', 'fixture', 'pi_claim', 'buyer@example.test'),
    ('cs_test_limited', 'sandbox', 'fixture', 'pi_limited', 'buyer@example.test'),
    ('cs_test_conflict', 'sandbox', 'fixture', 'pi_conflict', 'buyer@example.test');

DO $$
DECLARE
  v_account uuid := 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  v_vault uuid := 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
  v_device uuid := 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
  v_count integer;
  v_index integer;
BEGIN
  IF NOT hosted.issue_enrollment_challenge('cs_test_claim', 'sandbox',
    repeat('a', 64)) THEN RAISE EXCEPTION 'first issue failed'; END IF;
  IF hosted.issue_enrollment_challenge('cs_test_claim', 'sandbox',
    repeat('b', 64)) THEN RAISE EXCEPTION 'immediate email replay accepted'; END IF;
  IF hosted.record_enrollment_challenge_delivery(repeat('a', 64), 'unsafe') THEN
    RAISE EXCEPTION 'bad mail result accepted'; END IF;
  IF hosted.claim_and_pair_first_device(repeat('a', 64), 'cs_test_claim',
    'sandbox', v_account, v_vault, v_device, repeat('e', 64)) IS NOT NULL THEN
    RAISE EXCEPTION 'unsent challenge claimed account'; END IF;
  IF NOT hosted.record_enrollment_challenge_delivery(repeat('a', 64), 'sent') THEN
    RAISE EXCEPTION 'accepted mail not recorded'; END IF;
  IF hosted.record_enrollment_challenge_delivery(repeat('a', 64), 'sent') THEN
    RAISE EXCEPTION 'mail result replay accepted'; END IF;
  IF hosted.claim_and_pair_first_device(repeat('b', 64), 'cs_test_claim',
    'sandbox', v_account, v_vault, v_device, repeat('e', 64)) IS NOT NULL OR
     hosted.claim_and_pair_first_device(repeat('a', 64), 'cs_test_claim',
    'live', v_account, v_vault, v_device, repeat('e', 64)) IS NOT NULL THEN
    RAISE EXCEPTION 'wrong code or environment claimed account'; END IF;
  IF hosted.claim_and_pair_first_device(repeat('a', 64), 'cs_test_claim',
    'sandbox', v_account, v_vault, v_device, repeat('e', 64)) <> v_account THEN
    RAISE EXCEPTION 'valid challenge failed'; END IF;
  IF hosted.claim_and_pair_first_device(repeat('a', 64), 'cs_test_claim',
    'sandbox', 'dddddddd-dddd-4ddd-8ddd-dddddddddddd', v_vault,
    v_device, repeat('f', 64)) IS NOT NULL OR
     hosted.issue_enrollment_challenge('cs_test_claim', 'sandbox',
    repeat('c', 64)) THEN RAISE EXCEPTION 'claimed purchase replay accepted'; END IF;
  SELECT allowance_bytes INTO v_count FROM hosted.accounts
    WHERE account_id = v_account;
  IF v_count <> 0 THEN RAISE EXCEPTION 'unpaid account granted capacity'; END IF;
  IF NOT EXISTS (SELECT 1 FROM hosted.vaults WHERE account_id = v_account
      AND vault_id = v_vault) OR NOT EXISTS (
    SELECT 1 FROM hosted.device_sessions WHERE account_id = v_account
      AND vault_id = v_vault AND device_id = v_device
      AND token_hash = repeat('e', 64) AND revoked_at IS NULL
      AND expires_at > clock_timestamp()) THEN
    RAISE EXCEPTION 'first device was not paired atomically';
  END IF;

  IF NOT hosted.issue_enrollment_challenge('cs_test_conflict', 'sandbox',
      repeat('7', 64)) OR NOT hosted.record_enrollment_challenge_delivery(
      repeat('7', 64), 'sent') THEN
    RAISE EXCEPTION 'collision fixture setup failed';
  END IF;
  BEGIN
    PERFORM hosted.claim_and_pair_first_device(repeat('7', 64),
      'cs_test_conflict', 'sandbox',
      '99999999-9999-4999-8999-999999999999',
      '88888888-8888-4888-8888-888888888888',
      '77777777-7777-4777-8777-777777777777', repeat('e', 64));
    RAISE EXCEPTION 'duplicate device digest accepted';
  EXCEPTION WHEN unique_violation THEN NULL; END;
  IF EXISTS (SELECT 1 FROM hosted.accounts WHERE account_id =
      '99999999-9999-4999-8999-999999999999') OR EXISTS (
    SELECT 1 FROM hosted.enrollment_challenges WHERE
      purchase_session_id = 'cs_test_conflict' AND consumed_at IS NOT NULL) THEN
    RAISE EXCEPTION 'failed pairing left half-created buyer';
  END IF;

  FOR v_index IN 1..5 LOOP
    IF v_index > 1 THEN
      UPDATE hosted.enrollment_challenges SET
        created_at = now() - interval '11 minutes',
        expires_at = now() - interval '1 minute'
        WHERE purchase_session_id = 'cs_test_limited';
    END IF;
    IF NOT hosted.issue_enrollment_challenge('cs_test_limited', 'sandbox',
      lpad(to_hex(v_index), 64, '0')) THEN
      RAISE EXCEPTION 'allowed request % refused', v_index;
    END IF;
  END LOOP;
  IF NOT hosted.record_enrollment_challenge_delivery(
      lpad(to_hex(5), 64, '0'), 'sent') THEN
    RAISE EXCEPTION 'fifth email delivery not recorded';
  END IF;
  UPDATE hosted.enrollment_challenges SET
    created_at = now() - interval '11 minutes',
    expires_at = now() - interval '1 minute'
    WHERE purchase_session_id = 'cs_test_limited';
  IF hosted.issue_enrollment_challenge('cs_test_limited', 'sandbox',
    repeat('f', 64)) THEN RAISE EXCEPTION 'sixth daily email accepted'; END IF;
  IF hosted.claim_and_pair_first_device(lpad(to_hex(5), 64, '0'),
    'cs_test_limited', 'sandbox',
    'dddddddd-dddd-4ddd-8ddd-dddddddddddd', v_vault, v_device,
    repeat('f', 64)) IS NOT NULL THEN
    RAISE EXCEPTION 'expired challenge claimed account'; END IF;
  SELECT requests_in_window INTO v_count FROM hosted.enrollment_challenges
    WHERE purchase_session_id = 'cs_test_limited';
  IF v_count <> 5 THEN RAISE EXCEPTION 'email rate counter drifted'; END IF;
END;
$$;
ROLLBACK;
