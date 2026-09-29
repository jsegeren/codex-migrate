-- Disposable PostgreSQL only, after hosted 0030. No buyer or R2 state.
BEGIN;
INSERT INTO commerce_purchases (session_id, mode, release_id, payment_intent, email)
  VALUES ('cs_test_rotation', 'sandbox', 'fixture', 'pi_rotation', 'buyer@example.test');
INSERT INTO hosted.accounts (account_id, allowance_bytes)
  VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 0);
INSERT INTO hosted.purchase_enrollments
  (account_id, purchase_session_id, purchase_mode)
  VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'cs_test_rotation', 'sandbox');
INSERT INTO hosted.vaults (account_id, vault_id)
  VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb');
INSERT INTO hosted.device_sessions
  (token_hash, account_id, vault_id, device_id, expires_at)
  VALUES (repeat('a', 64), 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    'cccccccc-cccc-4ccc-8ccc-cccccccccccc', now() + interval '1 day');

DO $$
DECLARE
  v_account uuid := 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  v_vault uuid := 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
  v_old uuid := 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
  v_new uuid := 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
  v_second uuid := 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';
  v_rotated_account uuid;
  v_rotated_vault uuid;
BEGIN
  IF EXISTS (SELECT 1 FROM hosted.rotate_device_session(
      repeat('f', 64), v_old, repeat('b', 64), v_new)) OR
     EXISTS (SELECT 1 FROM hosted.rotate_device_session(
      repeat('a', 64), v_second, repeat('b', 64), v_new)) OR
     EXISTS (SELECT 1 FROM hosted.rotate_device_session(
      repeat('a', 64), v_old, repeat('a', 64), v_new)) OR
     EXISTS (SELECT 1 FROM hosted.rotate_device_session(
      repeat('a', 64), v_old, repeat('b', 64), v_old)) THEN
    RAISE EXCEPTION 'invalid rotation was accepted';
  END IF;

  SELECT rotated.account_id, rotated.vault_id
    INTO v_rotated_account, v_rotated_vault
    FROM hosted.rotate_device_session(
      repeat('a', 64), v_old, repeat('b', 64), v_new) AS rotated;
  IF v_rotated_account IS DISTINCT FROM v_account OR
     v_rotated_vault IS DISTINCT FROM v_vault OR
     EXISTS (SELECT 1 FROM hosted.device_sessions
       WHERE token_hash = repeat('a', 64) AND revoked_at IS NULL) OR
     NOT EXISTS (SELECT 1 FROM hosted.device_sessions
       WHERE token_hash = repeat('b', 64) AND account_id = v_account
         AND vault_id = v_vault AND device_id = v_new
         AND revoked_at IS NULL
         AND expires_at BETWEEN clock_timestamp() + interval '28 days'
                            AND clock_timestamp() + interval '30 days') THEN
    RAISE EXCEPTION 'rotation did not replace one scoped device';
  END IF;
  IF EXISTS (SELECT 1 FROM hosted.rotate_device_session(
      repeat('a', 64), v_old, repeat('c', 64), v_second)) OR
     (SELECT count(*) FROM hosted.device_sessions
       WHERE account_id = v_account AND vault_id = v_vault
         AND revoked_at IS NULL AND expires_at > clock_timestamp()) <> 1 THEN
    RAISE EXCEPTION 'old bearer replayed or active count changed';
  END IF;

  -- A conflicting new digest must roll back revocation of its old bearer.
  INSERT INTO hosted.device_sessions
    (token_hash, account_id, vault_id, device_id, expires_at)
    VALUES (repeat('c', 64), v_account, v_vault, v_second,
      clock_timestamp() + interval '2 days');
  BEGIN
    PERFORM hosted.rotate_device_session(
      repeat('b', 64), v_new, repeat('c', 64), v_old);
    RAISE EXCEPTION 'duplicate new bearer was accepted';
  EXCEPTION WHEN unique_violation THEN NULL; END;
  IF NOT EXISTS (SELECT 1 FROM hosted.device_sessions
      WHERE token_hash = repeat('b', 64) AND revoked_at IS NULL) THEN
    RAISE EXCEPTION 'failed rotation revoked the old bearer';
  END IF;
  UPDATE hosted.device_sessions
    SET created_at = clock_timestamp() - interval '2 days',
        expires_at = clock_timestamp() - interval '1 second'
    WHERE token_hash = repeat('b', 64);
  IF EXISTS (SELECT 1 FROM hosted.rotate_device_session(
      repeat('b', 64), v_new, repeat('d', 64), v_old)) THEN
    RAISE EXCEPTION 'expired bearer rotated';
  END IF;
END;
$$;
ROLLBACK;
