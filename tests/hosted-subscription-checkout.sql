-- Disposable PostgreSQL only. Never use these synthetic rows as service proof.
BEGIN;
INSERT INTO commerce_purchases (session_id, mode, release_id, payment_intent, email)
  VALUES ('cs_test_checkout', 'sandbox', 'fixture', 'pi_checkout', 'fixture@example.test');
INSERT INTO hosted.accounts (account_id, allowance_bytes)
  VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 0);
INSERT INTO hosted.purchase_enrollments (account_id, purchase_session_id, purchase_mode)
  VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'cs_test_checkout', 'sandbox');
DO $$
DECLARE
  v_first record;
  v_retry record;
  v_account uuid := 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  v_site text := 'https://codex-migrate-fixture-joshuas-projects-d3a5c48d.vercel.app';
BEGIN
  SELECT * INTO v_first FROM hosted.reserve_subscription_checkout(
    v_account, 'price_fixture', 1000, 1000000, v_site);
  IF v_first.attempt_id IS NULL OR NOT v_first.retry_allowed THEN
    RAISE EXCEPTION 'durable checkout attempt missing'; END IF;
  SELECT * INTO v_retry FROM hosted.reserve_subscription_checkout(
    v_account, 'price_fixture', 1000, 1000000, v_site);
  IF v_retry.attempt_id <> v_first.attempt_id THEN RAISE EXCEPTION 'retry changed idempotency key'; END IF;
  IF EXISTS (SELECT 1 FROM hosted.reserve_subscription_checkout(
    v_account, 'price_changed', 1000, 1000000, v_site)) THEN
    RAISE EXCEPTION 'frozen checkout price changed'; END IF;
  IF hosted.record_subscription_checkout(v_account, gen_random_uuid(), 'cs_test_wrong') THEN
    RAISE EXCEPTION 'foreign attempt recorded'; END IF;
  IF hosted.record_subscription_checkout(v_account, v_first.attempt_id, 'cs_live_wrong') THEN
    RAISE EXCEPTION 'live session recorded'; END IF;
  IF NOT hosted.record_subscription_checkout(v_account, v_first.attempt_id, 'cs_test_owned') OR
     NOT hosted.record_subscription_checkout(v_account, v_first.attempt_id, 'cs_test_owned') THEN
    RAISE EXCEPTION 'session record is not idempotent'; END IF;
  IF hosted.record_subscription_checkout(v_account, v_first.attempt_id, 'cs_test_other') THEN
    RAISE EXCEPTION 'checkout overwritten'; END IF;
  IF hosted.enroll_checkout_subscription(v_account, v_first.attempt_id,
    'cs_test_other', 'sub_owned', 'cus_owned') THEN RAISE EXCEPTION 'foreign session enrolled'; END IF;
  IF NOT hosted.enroll_checkout_subscription(v_account, v_first.attempt_id,
    'cs_test_owned', 'sub_owned', 'cus_owned') OR NOT hosted.enroll_checkout_subscription(
    v_account, v_first.attempt_id, 'cs_test_owned', 'sub_owned', 'cus_owned') THEN
    RAISE EXCEPTION 'enrollment not idempotent'; END IF;
  IF hosted.enroll_checkout_subscription(v_account, v_first.attempt_id,
    'cs_test_owned', 'sub_other', 'cus_owned') THEN RAISE EXCEPTION 'subscription silently replaced'; END IF;
  UPDATE hosted.subscription_checkout_attempts SET created_at = clock_timestamp() - interval '24 hours'
    WHERE account_id = v_account;
  SELECT * INTO v_retry FROM hosted.reserve_subscription_checkout(
    v_account, 'price_fixture', 1000, 1000000, v_site);
  IF v_retry.retry_allowed OR v_retry.attempt_id <> v_first.attempt_id OR
     v_retry.session_id <> 'cs_test_owned' THEN RAISE EXCEPTION 'old attempt reset'; END IF;
  IF EXISTS (SELECT 1 FROM hosted.reserve_subscription_checkout(gen_random_uuid(),
    'price_fixture', 1000, 1000000, v_site)) THEN RAISE EXCEPTION 'unowned account checkout'; END IF;
END;
$$;
ROLLBACK;
