-- Synthetic object-count acceptance near the Founder's measured two-Mac
-- first-backup inventory. No customer history, key, or digest is read.
BEGIN;
INSERT INTO hosted.accounts (account_id, allowance_bytes)
  VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 1000000);
INSERT INTO hosted.vaults (account_id, vault_id)
  VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
          'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb');

DO $$
DECLARE
  v_account uuid := 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  v_vault uuid := 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
  v_snapshot uuid := 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
  v_reservation uuid := 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
  v_prefix text := 'accounts/' || v_account || '/vaults/' || v_vault || '/';
  v_objects jsonb;
  v_retained bigint;
  v_count integer;
BEGIN
  SELECT jsonb_agg(item ORDER BY sequence) INTO v_objects FROM (
    SELECT 0 AS sequence, jsonb_build_object('key',
      v_prefix || 'metadata/' || v_snapshot || '.json',
      'bytes', 10, 'sha256', repeat('a', 64)) AS item
    UNION ALL
    SELECT i AS sequence, jsonb_build_object('key',
      v_prefix || 'objects/' || left(digest, 2) || '/' ||
      substring(digest from 3) || '.cvchunk', 'bytes', 10,
      'sha256', repeat('b', 64))
      FROM (SELECT i, lpad(to_hex(i), 64, '0') AS digest
        FROM generate_series(1, 36356) AS i) chunks
    UNION ALL
    SELECT 36357, jsonb_build_object('key',
      v_prefix || 'manifests/' || v_snapshot || '.cvmanifest',
      'bytes', 20, 'sha256', repeat('c', 64))
    UNION ALL
    SELECT 36358, jsonb_build_object('key',
      v_prefix || 'refs/' || v_snapshot || '.json',
      'bytes', 10, 'sha256', repeat('d', 64))
  ) listed;

  IF NOT hosted.reserve_upload(v_account, v_vault, v_reservation, 500000,
      clock_timestamp() + interval '15 minutes') THEN
    RAISE EXCEPTION 'scale reservation failed';
  END IF;
  IF NOT hosted.publish_verified_snapshot(v_account, v_vault,
      v_reservation, v_snapshot, v_objects) THEN
    RAISE EXCEPTION 'scale publication failed';
  END IF;
  SELECT retained_bytes INTO v_retained FROM hosted.accounts
    WHERE account_id = v_account;
  SELECT count(*) INTO v_count FROM hosted.snapshot_objects
    WHERE account_id = v_account AND vault_id = v_vault
      AND snapshot_id = v_snapshot;
  IF v_count <> 36359 OR v_retained <> 363600 THEN
    RAISE EXCEPTION 'scale inventory or usage mismatch';
  END IF;

  -- The Worker refuses request objects above 100,000,000 bytes. SQL must
  -- never publish an inventory the selected transport cannot have uploaded.
  UPDATE hosted.accounts SET allowance_bytes = 200000000
    WHERE account_id = v_account;
  IF NOT hosted.reserve_upload(v_account, v_vault,
      'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee', 100000003,
      clock_timestamp() + interval '15 minutes') THEN
    RAISE EXCEPTION 'oversize fixture reservation failed';
  END IF;
  BEGIN
    PERFORM hosted.publish_verified_snapshot(v_account, v_vault,
      'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
      'ffffffff-ffff-4fff-8fff-ffffffffffff',
      jsonb_build_array(
        jsonb_build_object('key', v_prefix ||
          'metadata/ffffffff-ffff-4fff-8fff-ffffffffffff.json',
          'bytes', 1, 'sha256', repeat('a', 64)),
        jsonb_build_object('key', v_prefix ||
          'manifests/ffffffff-ffff-4fff-8fff-ffffffffffff.cvmanifest',
          'bytes', 100000001, 'sha256', repeat('b', 64)),
        jsonb_build_object('key', v_prefix ||
          'refs/ffffffff-ffff-4fff-8fff-ffffffffffff.json',
          'bytes', 1, 'sha256', repeat('c', 64))));
    RAISE EXCEPTION 'oversize manifest was accepted';
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM <> 'hosted_publication_invalid' THEN RAISE; END IF;
  END;
END;
$$;
ROLLBACK;
