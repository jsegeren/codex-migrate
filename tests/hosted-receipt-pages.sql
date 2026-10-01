-- Disposable PostgreSQL only, after hosted migrations 0000-0008.
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
  v_metadata text;
  v_chunk text;
  v_manifest text;
  v_ref text;
  v_extra text;
  v_first jsonb;
  v_second jsonb;
  v_verified jsonb;
  v_count integer;
  v_bytes bigint;
  v_id uuid;
  v_rejected boolean;
BEGIN
  v_metadata := v_prefix || 'metadata/' || v_snapshot || '.json';
  v_chunk := v_prefix || 'objects/' || repeat('b', 2) || '/' || repeat('b', 62) || '.cvchunk';
  v_extra := v_prefix || 'objects/' || repeat('e', 2) || '/' || repeat('e', 62) || '.cvchunk';
  v_manifest := v_prefix || 'manifests/' || v_snapshot || '.cvmanifest';
  v_ref := v_prefix || 'refs/' || v_snapshot || '.json';
  IF NOT hosted.reserve_upload_current(v_account, v_vault,
      v_reservation, 60, now() + interval '15 minutes', 100) THEN
    RAISE EXCEPTION 'fixture reservation failed';
  END IF;
  v_first := jsonb_build_array(
    jsonb_build_object('key', v_metadata, 'bytes', 10, 'sha256', repeat('a', 64)),
    jsonb_build_object('key', v_chunk, 'bytes', 20, 'sha256', repeat('b', 64)));
  v_second := jsonb_build_array(
    jsonb_build_object('key', v_manifest, 'bytes', 5, 'sha256', repeat('c', 64)),
    jsonb_build_object('key', v_ref, 'bytes', 5, 'sha256', repeat('d', 64)));
  PERFORM hosted.append_receipt_page_current(v_account, v_vault,
    v_reservation, v_snapshot, v_first, 100);
  PERFORM hosted.append_receipt_page_current(v_account, v_vault,
    v_reservation, v_snapshot, v_first, 100);
  PERFORM hosted.append_receipt_page_current(v_account, v_vault,
    v_reservation, v_snapshot, v_second, 100);
  SELECT staged_count, staged_bytes, staged_snapshot_id
    INTO v_count, v_bytes, v_id FROM hosted.upload_reservations
    WHERE reservation_id = v_reservation;
  IF v_count <> 4 OR v_bytes <> 40 OR v_id <> v_snapshot OR
     (SELECT count(*) FROM hosted.staged_receipt_objects
       WHERE reservation_id = v_reservation) <> 4 THEN
    RAISE EXCEPTION 'paged receipt lost or duplicated an object';
  END IF;

  -- The first item in this page is new, the second conflicts. A page failure
  -- must roll back that first insert instead of leaving a partial claim.
  v_rejected := false;
  BEGIN
    PERFORM hosted.append_receipt_page_current(v_account, v_vault,
      v_reservation, v_snapshot, jsonb_build_array(
        jsonb_build_object('key', v_extra, 'bytes', 1, 'sha256', repeat('e', 64)),
        jsonb_build_object('key', v_metadata, 'bytes', 10, 'sha256', repeat('f', 64))), 100);
  EXCEPTION WHEN OTHERS THEN v_rejected := true;
  END;
  IF NOT v_rejected OR EXISTS (SELECT 1 FROM hosted.staged_receipt_objects
      WHERE reservation_id = v_reservation AND object_key = v_extra) THEN
    RAISE EXCEPTION 'conflicting page left a partial claim';
  END IF;

  v_rejected := false;
  BEGIN
    PERFORM hosted.append_receipt_page_current(v_account, v_vault,
      v_reservation, '22222222-2222-4222-8222-222222222222', v_first, 100);
  EXCEPTION WHEN OTHERS THEN v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'mixed snapshot page accepted'; END IF;
  v_rejected := false;
  BEGIN
    PERFORM hosted.append_receipt_page_current(v_account, v_vault,
      v_reservation, v_snapshot, jsonb_build_array(
        jsonb_build_object('key', v_extra, 'bytes', 61, 'sha256', repeat('e', 64))), 100);
  EXCEPTION WHEN OTHERS THEN v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'over-allowance page accepted'; END IF;
  v_rejected := false;
  BEGIN
    PERFORM hosted.append_receipt_page_current(v_account, v_vault,
      v_reservation, v_snapshot,
      (SELECT jsonb_agg(jsonb_build_object('key', v_extra, 'bytes', 1,
        'sha256', repeat('e', 64))) FROM generate_series(1, 513)), 100);
  EXCEPTION WHEN OTHERS THEN v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'oversized page accepted'; END IF;

  v_verified := v_first || v_second;
  v_rejected := false;
  BEGIN
    PERFORM hosted.publish_verified_staged_current(v_account, v_vault,
      v_reservation, v_snapshot,
      jsonb_build_array(v_first->0, jsonb_build_object('key', v_extra,
        'bytes', 20, 'sha256', repeat('e', 64)), v_second->0, v_second->1), 100);
  EXCEPTION WHEN OTHERS THEN v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'unstaged verified object published'; END IF;
  PERFORM hosted.publish_verified_staged_current(v_account, v_vault,
    v_reservation, v_snapshot, v_verified, 100);
  -- Same complete set is idempotent even after reservation publication.
  PERFORM hosted.publish_verified_staged_current(v_account, v_vault,
    v_reservation, v_snapshot, v_verified, 100);
  IF (SELECT last_good_snapshot_id FROM hosted.vaults
      WHERE account_id = v_account AND vault_id = v_vault) <> v_snapshot OR
     (SELECT retained_bytes FROM hosted.accounts
      WHERE account_id = v_account) <> 40 OR
     (SELECT count(*) FROM hosted.snapshot_objects
      WHERE account_id = v_account AND vault_id = v_vault AND
        snapshot_id = v_snapshot) <> 4 THEN
    RAISE EXCEPTION 'complete verified pages did not publish exactly once';
  END IF;
END;
$$;
ROLLBACK;
