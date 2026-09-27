-- Synthetic 21,910-object publication from durable provider-checkpoint rows.
-- This exercises the database finalization shape; the smaller fixture tests
-- the guarded per-page recorder. No customer history or keys are used.
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
BEGIN
  IF NOT hosted.reserve_upload_current(v_account, v_vault,
      v_reservation, 219100, clock_timestamp() + interval '15 minutes',
      500000) THEN
    RAISE EXCEPTION 'scale reservation failed';
  END IF;
  INSERT INTO hosted.staged_receipt_objects
    (reservation_id, object_key, object_bytes, sha256)
    SELECT v_reservation, object_key, 10, sha256 FROM (
      SELECT v_prefix || 'metadata/' || v_snapshot || '.json' AS object_key,
        repeat('a', 64) AS sha256
      UNION ALL
      SELECT v_prefix || 'objects/' || left(digest, 2) || '/' ||
        substring(digest from 3) || '.cvchunk', repeat('b', 64)
        FROM (SELECT lpad(to_hex(i), 64, '0') AS digest
          FROM generate_series(1, 21907) AS i) chunks
      UNION ALL
      SELECT v_prefix || 'manifests/' || v_snapshot || '.cvmanifest',
        repeat('c', 64)
      UNION ALL
      SELECT v_prefix || 'refs/' || v_snapshot || '.json', repeat('d', 64)
    ) objects;
  UPDATE hosted.upload_reservations SET staged_snapshot_id = v_snapshot,
    staged_count = 21910, staged_bytes = 219100,
    declared_count = 21910, declared_bytes = 219100
    WHERE reservation_id = v_reservation;
  INSERT INTO hosted.verified_receipt_objects
    (reservation_id, object_key, object_bytes, sha256)
    SELECT reservation_id, object_key, object_bytes, sha256
      FROM hosted.staged_receipt_objects
      WHERE reservation_id = v_reservation;
  IF NOT hosted.publish_checkpointed_staged_current(v_account, v_vault,
      v_reservation, v_snapshot, 500000) THEN
    RAISE EXCEPTION 'scale checkpoint publication failed';
  END IF;
  IF (SELECT count(*) FROM hosted.snapshot_objects WHERE
      account_id = v_account AND vault_id = v_vault AND
      snapshot_id = v_snapshot) <> 21910 OR
     (SELECT last_good_snapshot_id FROM hosted.vaults WHERE
      account_id = v_account AND vault_id = v_vault) <> v_snapshot THEN
    RAISE EXCEPTION 'scale verified inventory was incomplete';
  END IF;
END;
$$;
ROLLBACK;
