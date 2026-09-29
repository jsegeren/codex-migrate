-- Disposable PostgreSQL: only an exact, recent, published, same-Vault chunk
-- proof may be carried forward. Its provider timestamp must not be refreshed.
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
  v_old uuid := 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
  v_new uuid := 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
  v_other uuid := 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';
  v_third uuid := 'ffffffff-ffff-4fff-8fff-ffffffffffff';
  v_old_snapshot uuid := '11111111-1111-4111-8111-111111111111';
  v_new_snapshot uuid := '22222222-2222-4222-8222-222222222222';
  v_other_snapshot uuid := '33333333-3333-4333-8333-333333333333';
  v_third_snapshot uuid := '44444444-4444-4444-8444-444444444444';
  v_prefix text := 'accounts/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/vaults/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/';
  v_chunk text := 'objects/00/' || repeat('0', 62) || '.cvchunk';
  v_old_page jsonb;
  v_new_page jsonb;
  v_other_page jsonb;
  v_third_page jsonb;
  v_before timestamptz;
  v_after timestamptz;
  v_rejected boolean := false;
BEGIN
  v_old_page := jsonb_build_array(
    jsonb_build_object('key', v_prefix || 'metadata/' || v_old_snapshot || '.json',
      'bytes', 10, 'sha256', repeat('a', 64)),
    jsonb_build_object('key', v_prefix || 'manifests/' || v_old_snapshot || '.cvmanifest',
      'bytes', 10, 'sha256', repeat('b', 64)),
    jsonb_build_object('key', v_prefix || 'refs/' || v_old_snapshot || '.json',
      'bytes', 10, 'sha256', repeat('c', 64)),
    jsonb_build_object('key', v_prefix || v_chunk,
      'bytes', 10, 'sha256', repeat('d', 64)));
  v_new_page := jsonb_build_array(
    jsonb_build_object('key', v_prefix || 'metadata/' || v_new_snapshot || '.json',
      'bytes', 10, 'sha256', repeat('e', 64)),
    jsonb_build_object('key', v_prefix || 'manifests/' || v_new_snapshot || '.cvmanifest',
      'bytes', 10, 'sha256', repeat('f', 64)),
    jsonb_build_object('key', v_prefix || 'refs/' || v_new_snapshot || '.json',
      'bytes', 10, 'sha256', repeat('1', 64)),
    jsonb_build_object('key', v_prefix || v_chunk,
      'bytes', 10, 'sha256', repeat('d', 64)));
  IF NOT hosted.reserve_upload_current(v_account, v_vault, v_old,
      40, clock_timestamp() + interval '15 minutes', 100) THEN
    RAISE EXCEPTION 'old reservation failed';
  END IF;
  PERFORM hosted.append_receipt_page_declared_current(v_account, v_vault,
    v_old, v_old_snapshot, v_old_page, 4, 40, 100);
  IF hosted.reuse_recent_published_chunk_proofs_current(v_account, v_vault,
      v_old, v_old_snapshot, 100) <> 0 THEN
    RAISE EXCEPTION 'unpublished proof reused';
  END IF;
  PERFORM hosted.record_verified_receipt_page_current(v_account, v_vault,
    v_old, v_old_snapshot, v_old_page, 100);
  IF hosted.reuse_recent_published_chunk_proofs_current(v_account, v_vault,
      v_old, v_old_snapshot, 100) <> 0 THEN
    RAISE EXCEPTION 'self proof reused';
  END IF;
  IF NOT hosted.publish_checkpointed_staged_current(v_account, v_vault,
      v_old, v_old_snapshot, 100) THEN
    RAISE EXCEPTION 'source publication failed';
  END IF;
  UPDATE hosted.verified_receipt_objects SET
    verified_at = clock_timestamp() - interval '2 hours'
    WHERE reservation_id = v_old AND object_key = v_prefix || v_chunk;
  SELECT verified_at INTO v_before FROM hosted.verified_receipt_objects
    WHERE reservation_id = v_old AND object_key = v_prefix || v_chunk;
  IF NOT hosted.reserve_upload_current(v_account, v_vault, v_new,
      40, clock_timestamp() + interval '15 minutes', 100) THEN
    RAISE EXCEPTION 'new reservation failed';
  END IF;
  PERFORM hosted.append_receipt_page_declared_current(v_account, v_vault,
    v_new, v_new_snapshot, v_new_page, 4, 40, 100);
  IF hosted.reuse_recent_published_chunk_proofs_current(v_account, v_vault,
      v_new, v_new_snapshot, 100) <> 1 THEN
    RAISE EXCEPTION 'exact published proof not reused';
  END IF;
  SELECT verified_at INTO v_after FROM hosted.verified_receipt_objects
    WHERE reservation_id = v_new AND object_key = v_prefix || v_chunk;
  IF v_after <> v_before OR
     (SELECT count(*) FROM hosted.verified_receipt_objects
       WHERE reservation_id = v_new) <> 1 THEN
    RAISE EXCEPTION 'proof timestamp refreshed or metadata reused';
  END IF;
  BEGIN
    PERFORM hosted.publish_checkpointed_staged_current(v_account, v_vault,
      v_new, v_new_snapshot, 100);
  EXCEPTION WHEN OTHERS THEN v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'partial target published'; END IF;
  UPDATE hosted.verified_receipt_objects SET
    verified_at = clock_timestamp() - interval '25 hours'
    WHERE reservation_id = v_old AND object_key = v_prefix || v_chunk;
  UPDATE hosted.verified_receipt_objects SET
    verified_at = clock_timestamp() - interval '25 hours'
    WHERE reservation_id = v_new AND object_key = v_prefix || v_chunk;
  IF hosted.reuse_recent_published_chunk_proofs_current(v_account, v_vault,
      v_new, v_new_snapshot, 100) <> 0 THEN
    RAISE EXCEPTION 'expired provider proof reused';
  END IF;
  UPDATE hosted.verified_receipt_objects SET
    verified_at = clock_timestamp() - interval '2 hours'
    WHERE reservation_id = v_old AND object_key = v_prefix || v_chunk;
  -- A newer published snapshot without the old chunk prevents a scan through
  -- historical versions for a convenient but non-current proof.
  v_other_page := jsonb_build_array(
    jsonb_build_object('key', v_prefix || 'metadata/' || v_other_snapshot || '.json',
      'bytes', 10, 'sha256', repeat('2', 64)),
    jsonb_build_object('key', v_prefix || 'manifests/' || v_other_snapshot || '.cvmanifest',
      'bytes', 10, 'sha256', repeat('3', 64)),
    jsonb_build_object('key', v_prefix || 'refs/' || v_other_snapshot || '.json',
      'bytes', 10, 'sha256', repeat('4', 64)),
    jsonb_build_object('key', v_prefix || 'objects/11/' || repeat('1', 62) || '.cvchunk',
      'bytes', 10, 'sha256', repeat('5', 64)));
  IF NOT hosted.reserve_upload_current(v_account, v_vault, v_other,
      40, clock_timestamp() + interval '15 minutes', 200) THEN
    RAISE EXCEPTION 'later reservation failed';
  END IF;
  PERFORM hosted.append_receipt_page_declared_current(v_account, v_vault,
    v_other, v_other_snapshot, v_other_page, 4, 40, 200);
  PERFORM hosted.record_verified_receipt_page_current(v_account, v_vault,
    v_other, v_other_snapshot, v_other_page, 200);
  IF NOT hosted.publish_checkpointed_staged_current(v_account, v_vault,
      v_other, v_other_snapshot, 200) THEN
    RAISE EXCEPTION 'later publication failed';
  END IF;
  v_third_page := jsonb_build_array(
    jsonb_build_object('key', v_prefix || 'metadata/' || v_third_snapshot || '.json',
      'bytes', 10, 'sha256', repeat('6', 64)),
    jsonb_build_object('key', v_prefix || 'manifests/' || v_third_snapshot || '.cvmanifest',
      'bytes', 10, 'sha256', repeat('7', 64)),
    jsonb_build_object('key', v_prefix || 'refs/' || v_third_snapshot || '.json',
      'bytes', 10, 'sha256', repeat('8', 64)),
    jsonb_build_object('key', v_prefix || v_chunk,
      'bytes', 10, 'sha256', repeat('d', 64)));
  IF NOT hosted.reserve_upload_current(v_account, v_vault, v_third,
      40, clock_timestamp() + interval '15 minutes', 200) THEN
    RAISE EXCEPTION 'third reservation failed';
  END IF;
  PERFORM hosted.append_receipt_page_declared_current(v_account, v_vault,
    v_third, v_third_snapshot, v_third_page, 4, 40, 200);
  IF hosted.reuse_recent_published_chunk_proofs_current(v_account, v_vault,
      v_third, v_third_snapshot, 200) <> 0 THEN
    RAISE EXCEPTION 'older snapshot proof reused';
  END IF;
END;
$$;
ROLLBACK;
