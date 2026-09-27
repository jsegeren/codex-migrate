-- Run only against a disposable PostgreSQL database after 0000_capacity.sql.
-- Nothing in this file should point at a live commerce environment.
BEGIN;
INSERT INTO hosted.accounts (account_id, allowance_bytes)
VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 100);
INSERT INTO hosted.vaults (account_id, vault_id) VALUES
  ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'),
  ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'cccccccc-cccc-4ccc-8ccc-cccccccccccc');

DO $$
DECLARE
  v_account_id uuid := 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  first_vault uuid := 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
  second_vault uuid := 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
  first_reservation uuid := 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
  current_reserved bigint;
BEGIN
  IF NOT hosted.reserve_upload(v_account_id, first_vault, first_reservation,
      60, now() + interval '15 minutes') THEN
    RAISE EXCEPTION 'first reservation failed';
  END IF;

  -- A reservation ID collision must roll back its provisional quota update.
  BEGIN
    PERFORM hosted.reserve_upload(v_account_id, first_vault, first_reservation,
      10, now() + interval '15 minutes');
    RAISE EXCEPTION 'duplicate reservation was accepted';
  EXCEPTION WHEN unique_violation THEN NULL;
  END;
  SELECT reserved_bytes INTO current_reserved FROM hosted.accounts
    WHERE hosted.accounts.account_id = v_account_id;
  IF current_reserved <> 60 THEN RAISE EXCEPTION 'collision leaked quota'; END IF;

  IF NOT hosted.reserve_upload(v_account_id, second_vault,
      'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee', 40,
      now() + interval '15 minutes') THEN
    RAISE EXCEPTION 'second Vault should share the remaining allowance';
  END IF;
  IF hosted.reserve_upload(v_account_id, first_vault,
      'ffffffff-ffff-4fff-8fff-ffffffffffff', 1,
      now() + interval '15 minutes') THEN
    RAISE EXCEPTION 'over-limit reservation was accepted';
  END IF;
  IF hosted.reserve_upload(v_account_id, '99999999-9999-4999-8999-999999999999',
      '88888888-8888-4888-8888-888888888888', 1,
      now() + interval '15 minutes') THEN
    RAISE EXCEPTION 'unowned Vault was accepted';
  END IF;
  IF hosted.reserve_upload(v_account_id, first_vault,
      '77777777-7777-4777-8777-777777777777', 1,
      now() + interval '2 hours') THEN
    RAISE EXCEPTION 'long-lived reservation was accepted';
  END IF;
  SELECT reserved_bytes INTO current_reserved FROM hosted.accounts
    WHERE hosted.accounts.account_id = v_account_id;
  IF current_reserved <> 100 THEN RAISE EXCEPTION 'quota drift'; END IF;

  -- Downgrading below existing usage blocks new grants without deleting data.
  UPDATE hosted.accounts SET allowance_bytes = 50
    WHERE hosted.accounts.account_id = v_account_id;
  IF hosted.reserve_upload(v_account_id, first_vault,
      '66666666-6666-4666-8666-666666666666', 1,
      now() + interval '15 minutes') THEN
    RAISE EXCEPTION 'downgraded account accepted upload';
  END IF;

  -- Corrupt or stale counters must fail closed without bigint overflow.
  UPDATE hosted.accounts SET allowance_bytes = 9223372036854775807,
    retained_bytes = 9223372036854775807,
    reserved_bytes = 9223372036854775807
    WHERE hosted.accounts.account_id = v_account_id;
  IF hosted.reserve_upload(v_account_id, first_vault,
      '55555555-5555-4555-8555-555555555555', 1,
      now() + interval '15 minutes') THEN
    RAISE EXCEPTION 'overflowing account accepted upload';
  END IF;
END;
$$;
ROLLBACK;
