-- Dark, sandbox-only checkout ownership. One durable attempt per purchased
-- account; no automatic retry/reset after Stripe's idempotency retention may
-- expire. Review/reconciliation is required instead of risking two charges.
CREATE TABLE hosted.subscription_checkout_attempts (
  account_id uuid PRIMARY KEY,
  mode text NOT NULL DEFAULT 'sandbox' CHECK (mode = 'sandbox'),
  attempt_id uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(),
  price_id text NOT NULL CHECK (price_id ~ '^price_[A-Za-z0-9]+$'),
  price_cents integer NOT NULL CHECK (price_cents BETWEEN 1000 AND 9999999),
  allowance_bytes bigint NOT NULL CHECK (allowance_bytes BETWEEN 1 AND 1000000000000),
  policy text NOT NULL DEFAULT 'sandbox-monthly-30-day-trial-v1'
    CHECK (policy = 'sandbox-monthly-30-day-trial-v1'),
  site text NOT NULL CHECK (site ~ '^https://codex-migrate-[a-z0-9]+-joshuas-projects-d3a5c48d[.]vercel[.]app$'),
  session_id text UNIQUE CHECK (session_id ~ '^cs_test_[A-Za-z0-9]+$'),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  FOREIGN KEY (account_id, mode)
    REFERENCES hosted.purchase_enrollments (account_id, purchase_mode)
);
--> statement-breakpoint
CREATE FUNCTION hosted.reserve_subscription_checkout(
  p_account uuid, p_price text, p_cents integer, p_allowance bigint, p_site text
) RETURNS TABLE(account_id uuid, mode text, attempt_id uuid, price_id text,
  price_cents integer, allowance_bytes bigint, policy text, site text,
  session_id text, retry_allowed boolean)
LANGUAGE plpgsql AS $$
BEGIN
  PERFORM 1 FROM hosted.accounts AS a WHERE a.account_id = p_account
    AND a.owner_kind = 'individual' FOR UPDATE;
  IF NOT FOUND THEN RETURN; END IF;
  IF EXISTS (SELECT 1 FROM hosted.subscription_enrollments AS s
    WHERE s.account_id = p_account) AND NOT EXISTS (
      SELECT 1 FROM hosted.subscription_checkout_attempts AS a
      WHERE a.account_id = p_account) THEN RETURN; END IF;
  INSERT INTO hosted.subscription_checkout_attempts
    (account_id, price_id, price_cents, allowance_bytes, site)
    VALUES (p_account, p_price, p_cents, p_allowance, p_site)
    ON CONFLICT ON CONSTRAINT subscription_checkout_attempts_pkey DO NOTHING;
  RETURN QUERY SELECT a.account_id, a.mode, a.attempt_id, a.price_id,
    a.price_cents, a.allowance_bytes, a.policy, a.site, a.session_id,
    a.created_at > clock_timestamp() - interval '23 hours'
    FROM hosted.subscription_checkout_attempts AS a
    WHERE a.account_id = p_account AND a.price_id = p_price
      AND a.price_cents = p_cents AND a.allowance_bytes = p_allowance;
END;
$$;
--> statement-breakpoint
CREATE FUNCTION hosted.record_subscription_checkout(
  p_account uuid, p_attempt uuid, p_session text
) RETURNS boolean LANGUAGE plpgsql AS $$
BEGIN
  IF p_session IS NULL OR p_session !~ '^cs_test_[A-Za-z0-9]+$' THEN RETURN false; END IF;
  UPDATE hosted.subscription_checkout_attempts AS a SET session_id = p_session
    WHERE a.account_id = p_account AND a.attempt_id = p_attempt
      AND (a.session_id IS NULL OR a.session_id = p_session);
  RETURN FOUND;
END;
$$;
--> statement-breakpoint
CREATE FUNCTION hosted.enroll_checkout_subscription(
  p_account uuid, p_attempt uuid, p_session text, p_subscription text, p_customer text
) RETURNS boolean LANGUAGE plpgsql AS $$
DECLARE
  v_attempt hosted.subscription_checkout_attempts%ROWTYPE;
BEGIN
  IF p_subscription IS NULL OR p_subscription !~ '^sub_[A-Za-z0-9]+$' OR
     p_customer IS NULL OR p_customer !~ '^cus_[A-Za-z0-9]+$' THEN RETURN false; END IF;
  PERFORM 1 FROM hosted.accounts AS a WHERE a.account_id = p_account
    AND a.owner_kind = 'individual' FOR UPDATE;
  IF NOT FOUND THEN RETURN false; END IF;
  SELECT * INTO v_attempt FROM hosted.subscription_checkout_attempts AS a
    WHERE a.account_id = p_account AND a.attempt_id = p_attempt
      AND a.session_id = p_session FOR UPDATE;
  IF NOT FOUND THEN RETURN false; END IF;
  INSERT INTO hosted.subscription_enrollments
    (account_id, mode, subscription_id, customer_id, price_id)
    VALUES (p_account, 'sandbox', p_subscription, p_customer, v_attempt.price_id)
    ON CONFLICT (account_id) DO NOTHING;
  RETURN EXISTS (SELECT 1 FROM hosted.subscription_enrollments AS s
    WHERE s.account_id = p_account AND s.mode = 'sandbox'
      AND s.subscription_id = p_subscription AND s.customer_id = p_customer
      AND s.price_id = v_attempt.price_id);
END;
$$;
