-- Synthetic near-real object count through page admission and staged publish.
-- No customer content, keys, or hashes are read.
BEGIN;
INSERT INTO hosted.accounts (account_id, allowance_bytes)
  VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 500000);
INSERT INTO hosted.vaults (account_id, vault_id)
  VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb');

DO $$
DECLARE
  v_account uuid := 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  v_vault uuid := 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
  v_reservation uuid := 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
  v_snapshot uuid := '11111111-1111-4111-8111-111111111111';
  v_prefix text := 'accounts/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/vaults/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/';
  v_objects jsonb;
  v_page jsonb;
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
        FROM generate_series(1, 21907) AS i) chunks
    UNION ALL
    SELECT 21908, jsonb_build_object('key',
      v_prefix || 'manifests/' || v_snapshot || '.cvmanifest',
      'bytes', 20, 'sha256', repeat('c', 64))
    UNION ALL
    SELECT 21909, jsonb_build_object('key',
      v_prefix || 'refs/' || v_snapshot || '.json',
      'bytes', 10, 'sha256', repeat('d', 64))
  ) listed;
  IF NOT hosted.reserve_upload_current(v_account, v_vault, v_reservation,
      250000, clock_timestamp() + interval '15 minutes', 500000) THEN
    RAISE EXCEPTION 'scale reservation failed';
  END IF;
  FOR v_page IN
    SELECT jsonb_agg(value ORDER BY ordinal) FROM
      jsonb_array_elements(v_objects) WITH ORDINALITY AS item(value, ordinal)
      GROUP BY (ordinal - 1) / 512 ORDER BY (ordinal - 1) / 512
  LOOP
    PERFORM hosted.append_receipt_page_current(v_account, v_vault,
      v_reservation, v_snapshot, v_page, 500000);
  END LOOP;
  SELECT staged_count INTO v_count FROM hosted.upload_reservations
    WHERE reservation_id = v_reservation;
  IF v_count <> 21910 THEN RAISE EXCEPTION 'scale pages incomplete'; END IF;
  PERFORM hosted.publish_verified_staged_current(v_account, v_vault,
    v_reservation, v_snapshot, v_objects, 500000);
  IF (SELECT count(*) FROM hosted.snapshot_objects WHERE
      account_id = v_account AND vault_id = v_vault AND
      snapshot_id = v_snapshot) <> 21910 THEN
    RAISE EXCEPTION 'scale publication incomplete';
  END IF;
END;
$$;
ROLLBACK;
