-- Disposable PostgreSQL only, after commerce 0000 and hosted 0000-0004.
BEGIN;
INSERT INTO commerce_purchases (session_id, mode, release_id, payment_intent, email)
  VALUES ('cs_test_claim', 'sandbox', 'fixture', 'pi_claim', 'buyer@example.test'),
    ('cs_test_limited', 'sandbox', 'fixture', 'pi_limited', 'buyer@example.test');

DO $$
DECLARE
  v_account uuid := 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  v_count integer;
  v_index integer;
BEGIN
  IF NOT hosted.issue_enrollment_challenge('cs_test_claim', 'sandbox',
    repeat('a', 64)) THEN RAISE EXCEPTION 'first issue failed'; END IF;
  IF hosted.issue_enrollment_challenge('cs_test_claim', 'sandbox',
    repeat('b', 64)) THEN RAISE EXCEPTION 'immediate email replay accepted'; END IF;
  IF hosted.record_enrollment_challenge_delivery(repeat('a', 64), 'unsafe') THEN
    RAISE EXCEPTION 'bad mail result accepted'; END IF;
  IF hosted.claim_purchase_enrollment(repeat('a', 64), 'cs_test_claim',
    'sandbox', v_account) IS NOT NULL THEN
    RAISE EXCEPTION 'unsent challenge claimed account'; END IF;
  IF NOT hosted.record_enrollment_challenge_delivery(repeat('a', 64), 'sent') THEN
    RAISE EXCEPTION 'accepted mail not recorded'; END IF;
  IF hosted.record_enrollment_challenge_delivery(repeat('a', 64), 'sent') THEN
    RAISE EXCEPTION 'mail result replay accepted'; END IF;
  IF hosted.claim_purchase_enrollment(repeat('b', 64), 'cs_test_claim',
    'sandbox', v_account) IS NOT NULL OR
     hosted.claim_purchase_enrollment(repeat('a', 64), 'cs_test_claim',
    'live', v_account) IS NOT NULL THEN
    RAISE EXCEPTION 'wrong code or environment claimed account'; END IF;
  IF hosted.claim_purchase_enrollment(repeat('a', 64), 'cs_test_claim',
    'sandbox', v_account) <> v_account THEN
    RAISE EXCEPTION 'valid challenge failed'; END IF;
  IF hosted.claim_purchase_enrollment(repeat('a', 64), 'cs_test_claim',
    'sandbox', 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb') IS NOT NULL OR
     hosted.issue_enrollment_challenge('cs_test_claim', 'sandbox',
    repeat('c', 64)) THEN RAISE EXCEPTION 'claimed purchase replay accepted'; END IF;
  SELECT allowance_bytes INTO v_count FROM hosted.accounts
    WHERE account_id = v_account;
  IF v_count <> 0 THEN RAISE EXCEPTION 'unpaid account granted capacity'; END IF;

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
  IF hosted.claim_purchase_enrollment(lpad(to_hex(5), 64, '0'),
    'cs_test_limited', 'sandbox',
    'dddddddd-dddd-4ddd-8ddd-dddddddddddd') IS NOT NULL THEN
    RAISE EXCEPTION 'expired challenge claimed account'; END IF;
  SELECT requests_in_window INTO v_count FROM hosted.enrollment_challenges
    WHERE purchase_session_id = 'cs_test_limited';
  IF v_count <> 5 THEN RAISE EXCEPTION 'email rate counter drifted'; END IF;
END;
$$;
ROLLBACK;
