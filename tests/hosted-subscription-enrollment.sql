-- Disposable PostgreSQL only, after commerce and hosted migrations 0000-0013.
BEGIN;
INSERT INTO commerce_purchases (session_id, mode, release_id, payment_intent, email)
  VALUES ('cs_test_first', 'sandbox', 'fixture', 'pi_first', 'buyer@example.test'),
    ('cs_test_second', 'sandbox', 'fixture', 'pi_second', 'other@example.test');
INSERT INTO hosted.accounts (account_id, allowance_bytes) VALUES
  ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 0),
  ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', 0);
INSERT INTO hosted.purchase_enrollments
  (account_id, purchase_session_id, purchase_mode) VALUES
  ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'cs_test_first', 'sandbox'),
  ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', 'cs_test_second', 'sandbox');
INSERT INTO hosted.subscription_enrollments
  (account_id, mode, subscription_id, customer_id, price_id) VALUES
  ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'sandbox',
    'sub_first', 'cus_first', 'price_first');

DO $$
BEGIN
  BEGIN
    INSERT INTO hosted.subscription_enrollments
      (account_id, mode, subscription_id, customer_id, price_id) VALUES
      ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', 'live',
        'sub_second', 'cus_second', 'price_second');
    RAISE EXCEPTION 'cross-environment subscription enrollment accepted';
  EXCEPTION WHEN foreign_key_violation THEN NULL; END;
  BEGIN
    INSERT INTO hosted.subscription_enrollments
      (account_id, mode, subscription_id, customer_id, price_id) VALUES
      ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', 'sandbox',
        'sub_first', 'cus_second', 'price_second');
    RAISE EXCEPTION 'one subscription claimed by two accounts';
  EXCEPTION WHEN unique_violation THEN NULL; END;
  BEGIN
    INSERT INTO hosted.subscription_enrollments
      (account_id, mode, subscription_id, customer_id, price_id) VALUES
      ('cccccccc-cccc-4ccc-8ccc-cccccccccccc', 'sandbox',
        'sub_third', 'cus_third', 'price_third');
    RAISE EXCEPTION 'unclaimed account received subscription';
  EXCEPTION WHEN foreign_key_violation THEN NULL; END;
END;
$$;
ROLLBACK;
