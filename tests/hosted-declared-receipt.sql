-- Disposable PostgreSQL. An interrupted final page must not publish a
-- plausible-looking but incomplete set of independently verified objects.
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
  v_rejected boolean;
BEGIN
  v_first := jsonb_build_array(
    jsonb_build_object('key', v_prefix || 'metadata/' || v_snapshot || '.json',
      'bytes', 10, 'sha256', repeat('a', 64)),
    jsonb_build_object('key', v_prefix || 'manifests/' || v_snapshot || '.cvmanifest',
      'bytes', 10, 'sha256', repeat('b', 64)));
  v_last := jsonb_build_array(
    jsonb_build_object('key', v_prefix || 'refs/' || v_snapshot || '.json',
      'bytes', 10, 'sha256', repeat('c', 64)));
  IF NOT hosted.reserve_upload_current(v_account, v_vault,
      v_reservation, 30, clock_timestamp() + interval '15 minutes', 100) THEN
    RAISE EXCEPTION 'fixture reservation failed';
  END IF;
  PERFORM hosted.append_receipt_page_declared_current(v_account, v_vault,
    v_reservation, v_snapshot, v_first, 3, 30, 100);
  -- A lost acknowledgement may retry the exact page and declaration.
  PERFORM hosted.append_receipt_page_declared_current(v_account, v_vault,
    v_reservation, v_snapshot, v_first, 3, 30, 100);
  v_rejected := false;
  BEGIN
    PERFORM hosted.publish_declared_verified_staged_current(v_account, v_vault,
      v_reservation, v_snapshot, v_first, 100);
  EXCEPTION WHEN OTHERS THEN v_rejected := true;
  END;
  IF NOT v_rejected OR EXISTS (SELECT 1 FROM hosted.snapshots WHERE
      account_id = v_account AND vault_id = v_vault) THEN
    RAISE EXCEPTION 'missing final page published';
  END IF;
  v_rejected := false;
  BEGIN
    PERFORM hosted.append_receipt_page_declared_current(v_account, v_vault,
      v_reservation, v_snapshot, v_last, 4, 40, 100);
  EXCEPTION WHEN OTHERS THEN v_rejected := true;
  END;
  IF NOT v_rejected OR (SELECT staged_count FROM hosted.upload_reservations
      WHERE reservation_id = v_reservation) <> 2 THEN
    RAISE EXCEPTION 'changed declaration admitted a page';
  END IF;
  PERFORM hosted.append_receipt_page_declared_current(v_account, v_vault,
    v_reservation, v_snapshot, v_last, 3, 30, 100);
  IF (SELECT declared_count = staged_count AND declared_bytes = staged_bytes
      FROM hosted.upload_reservations WHERE reservation_id = v_reservation)
      IS DISTINCT FROM true THEN
    RAISE EXCEPTION 'complete declaration not recorded';
  END IF;
  PERFORM hosted.publish_declared_verified_staged_current(v_account, v_vault,
    v_reservation, v_snapshot, v_first || v_last, 100);
  IF (SELECT last_good_snapshot_id FROM hosted.vaults WHERE
      account_id = v_account AND vault_id = v_vault) <> v_snapshot THEN
    RAISE EXCEPTION 'complete verified declaration did not publish';
  END IF;
END;
$$;
ROLLBACK;
