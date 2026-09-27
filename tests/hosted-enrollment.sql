-- Disposable PostgreSQL only, after commerce 0000 and hosted 0000-0003.
BEGIN;
INSERT INTO commerce_purchases (session_id, mode, release_id, payment_intent, email)
  VALUES ('cs_test_first', 'sandbox', 'fixture', 'pi_first', 'buyer@example.test'),
    ('cs_test_second', 'sandbox', 'fixture', 'pi_second', 'buyer@example.test');
INSERT INTO hosted.accounts (account_id, allowance_bytes) VALUES
  ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 1000),
  ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', 1000),
  ('cccccccc-cccc-4ccc-8ccc-cccccccccccc', 1000);
INSERT INTO hosted.vaults (account_id, vault_id) VALUES
  ('cccccccc-cccc-4ccc-8ccc-cccccccccccc',
    'dddddddd-dddd-4ddd-8ddd-dddddddddddd');
INSERT INTO hosted.purchase_enrollments
  (account_id, purchase_session_id, purchase_mode)
  VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'cs_test_first', 'sandbox');

DO $$
BEGIN
  -- An unclaimed account may exist during setup, but cannot receive a device
  -- session and therefore cannot obtain an upload capability.
  BEGIN
    INSERT INTO hosted.device_sessions
      (token_hash, account_id, vault_id, device_id, expires_at)
      VALUES (repeat('f', 64),
        'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
        'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
        'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee', now() + interval '1 day');
    RAISE EXCEPTION 'unclaimed account received device session';
  EXCEPTION WHEN foreign_key_violation THEN NULL; END;

  -- A single paid purchase cannot mint a second hosted identity.
  BEGIN
    INSERT INTO hosted.purchase_enrollments
      (account_id, purchase_session_id, purchase_mode)
      VALUES ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', 'cs_test_first', 'sandbox');
    RAISE EXCEPTION 'duplicate purchase claimed';
  EXCEPTION WHEN unique_violation THEN NULL; END;

  -- Even if the same email bought twice, the account cannot silently merge
  -- the two purchase authorities.
  BEGIN
    INSERT INTO hosted.purchase_enrollments
      (account_id, purchase_session_id, purchase_mode)
      VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'cs_test_second', 'sandbox');
    RAISE EXCEPTION 'account claimed a second purchase';
  EXCEPTION WHEN unique_violation THEN NULL; END;

  BEGIN
    INSERT INTO hosted.purchase_enrollments
      (account_id, purchase_session_id, purchase_mode)
      VALUES ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', 'cs_test_missing', 'sandbox');
    RAISE EXCEPTION 'missing purchase accepted';
  EXCEPTION WHEN foreign_key_violation THEN NULL; END;

  BEGIN
    INSERT INTO hosted.purchase_enrollments
      (account_id, purchase_session_id, purchase_mode)
      VALUES ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', 'cs_test_first', 'live');
    RAISE EXCEPTION 'cross-environment purchase accepted';
  EXCEPTION WHEN foreign_key_violation THEN NULL; END;

  INSERT INTO hosted.purchase_enrollments
    (account_id, purchase_session_id, purchase_mode)
    VALUES ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', 'cs_test_second', 'sandbox');
END;
$$;
ROLLBACK;
