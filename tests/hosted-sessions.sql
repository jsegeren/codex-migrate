-- Run only against a disposable PostgreSQL database after migrations 0000-0002.
BEGIN;
INSERT INTO commerce_purchases (session_id, mode, release_id, payment_intent, email)
  VALUES ('cs_test_sessions', 'sandbox', 'fixture', 'pi_sessions', 'buyer@example.test');
INSERT INTO hosted.accounts (account_id, allowance_bytes)
  VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 1000);
INSERT INTO hosted.purchase_enrollments
  (account_id, purchase_session_id, purchase_mode)
  VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'cs_test_sessions', 'sandbox');
INSERT INTO hosted.vaults (account_id, vault_id) VALUES
  ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb');

INSERT INTO hosted.device_sessions
  (token_hash, account_id, vault_id, device_id, expires_at)
VALUES (repeat('a', 64), 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
  'cccccccc-cccc-4ccc-8ccc-cccccccccccc', now() + interval '1 day');

DO $$
DECLARE
  v_count integer;
BEGIN
  SELECT count(*) INTO v_count FROM hosted.device_sessions
    WHERE token_hash = repeat('a', 64)
      AND vault_id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
      AND revoked_at IS NULL AND expires_at > clock_timestamp();
  IF v_count <> 1 THEN RAISE EXCEPTION 'valid session inaccessible'; END IF;
  UPDATE hosted.device_sessions SET revoked_at = clock_timestamp()
    WHERE token_hash = repeat('a', 64);
  SELECT count(*) INTO v_count FROM hosted.device_sessions
    WHERE token_hash = repeat('a', 64)
      AND revoked_at IS NULL AND expires_at > clock_timestamp();
  IF v_count <> 0 THEN RAISE EXCEPTION 'revoked session accessible'; END IF;
  INSERT INTO hosted.device_sessions
    (token_hash, account_id, vault_id, device_id, created_at, expires_at)
  VALUES (repeat('d', 64), 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
    now() - interval '2 days', now() - interval '1 day');
  SELECT count(*) INTO v_count FROM hosted.device_sessions
    WHERE token_hash = repeat('d', 64)
      AND revoked_at IS NULL AND expires_at > clock_timestamp();
  IF v_count <> 0 THEN RAISE EXCEPTION 'expired session accessible'; END IF;
  BEGIN
    INSERT INTO hosted.device_sessions
      (token_hash, account_id, vault_id, device_id, expires_at)
    VALUES (repeat('b', 64), 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
      'cccccccc-cccc-4ccc-8ccc-cccccccccccc', now() + interval '31 days');
    RAISE EXCEPTION 'long session accepted';
  EXCEPTION WHEN check_violation THEN NULL; END;
  BEGIN
    INSERT INTO hosted.device_sessions
      (token_hash, account_id, vault_id, device_id, expires_at)
    VALUES (repeat('c', 64), 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
      'cccccccc-cccc-4ccc-8ccc-cccccccccccc', now() + interval '1 day');
    RAISE EXCEPTION 'foreign Vault session accepted';
  EXCEPTION WHEN foreign_key_violation THEN NULL; END;
END;
$$;
ROLLBACK;
