-- Disposable PostgreSQL only, after hosted 0017. No customer records or R2.
BEGIN;
INSERT INTO commerce_purchases (session_id, mode, release_id, payment_intent, email)
  VALUES ('cs_test_recovery', 'sandbox', 'fixture', 'pi_recovery', 'buyer@example.test');
INSERT INTO hosted.accounts (account_id, allowance_bytes)
  VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 0);
INSERT INTO hosted.purchase_enrollments
  (account_id, purchase_session_id, purchase_mode)
  VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'cs_test_recovery', 'sandbox');
INSERT INTO hosted.vaults (account_id, vault_id) VALUES
  ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'),
  ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'cccccccc-cccc-4ccc-8ccc-cccccccccccc');
INSERT INTO hosted.device_sessions
  (token_hash, account_id, vault_id, device_id, expires_at)
  VALUES (repeat('e', 64), 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    'dddddddd-dddd-4ddd-8ddd-dddddddddddd', now() + interval '20 days');

DO $$
DECLARE
  v_account uuid := 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  v_vault uuid := 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
  v_device uuid := 'ffffffff-ffff-4fff-8fff-ffffffffffff';
  v_count integer;
  v_index integer;
BEGIN
  IF hosted.issue_recovery_challenge('cs_test_missing', 'sandbox',
      repeat('a', 64)) OR
     NOT hosted.issue_recovery_challenge('cs_test_recovery', 'sandbox',
      repeat('a', 64)) OR
     hosted.issue_recovery_challenge('cs_test_recovery', 'sandbox',
      repeat('b', 64)) THEN
    RAISE EXCEPTION 'recovery challenge issue boundary failed';
  END IF;
  SELECT count(*) INTO v_count FROM hosted.list_recovery_vaults(
    repeat('a', 64), 'cs_test_recovery', 'sandbox');
  IF v_count <> 0 OR hosted.claim_recovery_vault_device(
      repeat('a', 64), 'cs_test_recovery', 'sandbox', v_vault,
      v_device, repeat('f', 64)) IS NOT NULL THEN
    RAISE EXCEPTION 'unsent challenge disclosed a Vault or paired a device';
  END IF;
  IF NOT hosted.record_recovery_challenge_delivery(repeat('a', 64), 'sent') OR
     hosted.record_recovery_challenge_delivery(repeat('a', 64), 'sent') THEN
    RAISE EXCEPTION 'mail delivery state was not one time';
  END IF;
  SELECT count(*) INTO v_count FROM hosted.list_recovery_vaults(
    repeat('a', 64), 'cs_test_recovery', 'sandbox');
  IF v_count <> 2 OR EXISTS (SELECT 1 FROM hosted.list_recovery_vaults(
      repeat('a', 64), 'cs_test_recovery', 'live')) OR
     EXISTS (SELECT 1 FROM hosted.list_recovery_vaults(
      repeat('b', 64), 'cs_test_recovery', 'sandbox')) THEN
    RAISE EXCEPTION 'recovery code listed the wrong Vaults';
  END IF;
  IF hosted.claim_recovery_vault_device(repeat('a', 64),
      'cs_test_recovery', 'sandbox',
      '99999999-9999-4999-8999-999999999999', v_device,
      repeat('f', 64)) IS NOT NULL OR
     hosted.claim_recovery_vault_device(repeat('a', 64),
      'cs_test_recovery', 'live', v_vault, v_device,
      repeat('f', 64)) IS NOT NULL THEN
    RAISE EXCEPTION 'wrong Vault or environment was paired';
  END IF;
  IF hosted.claim_recovery_vault_device(repeat('a', 64),
      'cs_test_recovery', 'sandbox', v_vault, v_device,
      repeat('f', 64)) <> v_account THEN
    RAISE EXCEPTION 'recovery device pairing failed';
  END IF;
  IF hosted.claim_recovery_vault_device(repeat('a', 64),
      'cs_test_recovery', 'sandbox', v_vault,
      '77777777-7777-4777-8777-777777777777', repeat('7', 64)) IS NOT NULL OR
     EXISTS (SELECT 1 FROM hosted.list_recovery_vaults(
      repeat('a', 64), 'cs_test_recovery', 'sandbox')) THEN
    RAISE EXCEPTION 'consumed recovery code was replayed';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM hosted.device_sessions
      WHERE account_id = v_account AND vault_id = v_vault
        AND device_id = v_device AND token_hash = repeat('f', 64)
        AND revoked_at IS NULL AND expires_at > clock_timestamp()) OR
     NOT EXISTS (SELECT 1 FROM hosted.device_sessions
      WHERE token_hash = repeat('e', 64) AND revoked_at IS NULL) OR
     (SELECT allowance_bytes FROM hosted.accounts WHERE account_id = v_account) <> 0 OR
     (SELECT count(*) FROM hosted.vaults WHERE account_id = v_account) <> 2 THEN
    RAISE EXCEPTION 'pairing changed an old device, capacity or Vault count';
  END IF;

  -- A failed insert rolls back code consumption; it must not strand a buyer.
  UPDATE hosted.recovery_challenges SET
    created_at = now() - interval '11 minutes',
    expires_at = now() - interval '1 minute'
    WHERE purchase_session_id = 'cs_test_recovery';
  IF NOT hosted.issue_recovery_challenge('cs_test_recovery', 'sandbox',
      repeat('b', 64)) OR
     NOT hosted.record_recovery_challenge_delivery(repeat('b', 64), 'sent') THEN
    RAISE EXCEPTION 'second challenge setup failed';
  END IF;
  BEGIN
    PERFORM hosted.claim_recovery_vault_device(repeat('b', 64),
      'cs_test_recovery', 'sandbox', v_vault,
      '88888888-8888-4888-8888-888888888888', repeat('e', 64));
    RAISE EXCEPTION 'duplicate device digest accepted';
  EXCEPTION WHEN unique_violation THEN NULL; END;
  IF EXISTS (SELECT 1 FROM hosted.recovery_challenges
      WHERE purchase_session_id = 'cs_test_recovery' AND consumed_at IS NOT NULL) THEN
    RAISE EXCEPTION 'failed pair consumed recovery code';
  END IF;

  FOR v_index IN 3..5 LOOP
    UPDATE hosted.recovery_challenges SET
      created_at = now() - interval '11 minutes',
      expires_at = now() - interval '1 minute'
      WHERE purchase_session_id = 'cs_test_recovery';
    IF NOT hosted.issue_recovery_challenge('cs_test_recovery', 'sandbox',
        lpad(to_hex(v_index), 64, '0')) THEN
      RAISE EXCEPTION 'allowed recovery email % refused', v_index;
    END IF;
  END LOOP;
  UPDATE hosted.recovery_challenges SET
    created_at = now() - interval '11 minutes',
    expires_at = now() - interval '1 minute'
    WHERE purchase_session_id = 'cs_test_recovery';
  IF hosted.issue_recovery_challenge('cs_test_recovery', 'sandbox',
      repeat('9', 64)) OR
     hosted.claim_recovery_vault_device(lpad(to_hex(5), 64, '0'),
      'cs_test_recovery', 'sandbox', v_vault,
      '77777777-7777-4777-8777-777777777777', repeat('7', 64)) IS NOT NULL THEN
    RAISE EXCEPTION 'daily email limit or expiry failed';
  END IF;
END;
$$;
ROLLBACK;
