-- Disposable PostgreSQL: interrupted verification cannot publish a partial or
-- stale snapshot, and retrying an exact verified page remains idempotent.
BEGIN;
INSERT INTO hosted.accounts (account_id, allowance_bytes)
  VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 100);
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
  v_first jsonb;
  v_last jsonb;
  v_bad jsonb;
  v_rejected boolean;
BEGIN
  v_first := jsonb_build_array(
    jsonb_build_object('key', v_prefix || 'metadata/' || v_snapshot || '.json',
      'bytes', 10, 'sha256', repeat('a', 64)),
    jsonb_build_object('key', v_prefix || 'objects/00/' || repeat('0', 62) || '.cvchunk',
      'bytes', 10, 'sha256', repeat('b', 64)));
  v_last := jsonb_build_array(
    jsonb_build_object('key', v_prefix || 'manifests/' || v_snapshot || '.cvmanifest',
      'bytes', 10, 'sha256', repeat('c', 64)),
    jsonb_build_object('key', v_prefix || 'refs/' || v_snapshot || '.json',
      'bytes', 10, 'sha256', repeat('d', 64)));
  IF NOT hosted.reserve_upload_current(v_account, v_vault,
      v_reservation, 40, clock_timestamp() + interval '15 minutes', 100) THEN
    RAISE EXCEPTION 'fixture reservation failed';
  END IF;
  PERFORM hosted.append_receipt_page_declared_current(v_account, v_vault,
    v_reservation, v_snapshot, v_first || v_last, 4, 40, 100);
  IF hosted.record_verified_receipt_page_current(v_account, v_vault,
      v_reservation, v_snapshot, v_first, 100) <> 2 THEN
    RAISE EXCEPTION 'first verified page failed';
  END IF;
  v_rejected := false;
  BEGIN
    PERFORM hosted.publish_checkpointed_staged_current(v_account, v_vault,
      v_reservation, v_snapshot, 100);
  EXCEPTION WHEN OTHERS THEN v_rejected := true;
  END;
  IF NOT v_rejected OR EXISTS (SELECT 1 FROM hosted.snapshots WHERE
      account_id = v_account AND vault_id = v_vault) THEN
    RAISE EXCEPTION 'partial verification published';
  END IF;
  v_bad := jsonb_build_array(jsonb_build_object('key',
    v_prefix || 'refs/' || v_snapshot || '.json', 'bytes', 10,
    'sha256', repeat('e', 64)));
  v_rejected := false;
  BEGIN
    PERFORM hosted.record_verified_receipt_page_current(v_account, v_vault,
      v_reservation, v_snapshot, v_bad, 100);
  EXCEPTION WHEN OTHERS THEN v_rejected := true;
  END;
  IF NOT v_rejected OR (SELECT count(*) FROM hosted.verified_receipt_objects
      WHERE reservation_id = v_reservation) <> 2 THEN
    RAISE EXCEPTION 'conflicting provider proof was admitted';
  END IF;
  PERFORM hosted.record_verified_receipt_page_current(v_account, v_vault,
    v_reservation, v_snapshot, v_first, 100);
  PERFORM hosted.record_verified_receipt_page_current(v_account, v_vault,
    v_reservation, v_snapshot, v_last, 100);
  UPDATE hosted.verified_receipt_objects SET
    verified_at = clock_timestamp() - interval '25 hours'
    WHERE reservation_id = v_reservation AND
      object_key = v_prefix || 'refs/' || v_snapshot || '.json';
  v_rejected := false;
  BEGIN
    PERFORM hosted.publish_checkpointed_staged_current(v_account, v_vault,
      v_reservation, v_snapshot, 100);
  EXCEPTION WHEN OTHERS THEN v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'stale proof published'; END IF;
  PERFORM hosted.record_verified_receipt_page_current(v_account, v_vault,
    v_reservation, v_snapshot, v_last, 100);
  IF NOT hosted.publish_checkpointed_staged_current(v_account, v_vault,
      v_reservation, v_snapshot, 100, 'complete') THEN
    RAISE EXCEPTION 'complete verified set failed to publish';
  END IF;
  IF (SELECT last_good_snapshot_id FROM hosted.vaults WHERE
      account_id = v_account AND vault_id = v_vault) <> v_snapshot OR
     (SELECT source_coverage FROM hosted.snapshots WHERE
      account_id = v_account AND vault_id = v_vault AND
      snapshot_id = v_snapshot) <> 'complete' OR
     (SELECT count(*) FROM hosted.snapshot_objects WHERE
      account_id = v_account AND vault_id = v_vault AND
      snapshot_id = v_snapshot) <> 4 THEN
    RAISE EXCEPTION 'last-good or complete inventory was not published';
  END IF;
  UPDATE hosted.verified_receipt_objects SET
    verified_at = clock_timestamp() - interval '25 hours'
    WHERE reservation_id = v_reservation;
  IF NOT hosted.publish_checkpointed_staged_current(v_account, v_vault,
      v_reservation, v_snapshot, 100, 'complete') THEN
    RAISE EXCEPTION 'same-snapshot retry after proof expiry failed';
  END IF;
  v_rejected := false;
  BEGIN
    PERFORM hosted.publish_checkpointed_staged_current(v_account, v_vault,
      v_reservation, v_snapshot, 100, 'needs_attention');
  EXCEPTION WHEN OTHERS THEN v_rejected := true;
  END;
  IF NOT v_rejected OR (SELECT source_coverage FROM hosted.snapshots WHERE
      account_id = v_account AND vault_id = v_vault AND
      snapshot_id = v_snapshot) <> 'complete' THEN
    RAISE EXCEPTION 'conflicting source coverage changed publication';
  END IF;
END;
$$;
ROLLBACK;
