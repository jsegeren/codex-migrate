-- Disposable PostgreSQL only, after hosted migrations 0000-0011.
BEGIN;
INSERT INTO hosted.accounts (account_id, allowance_bytes)
  VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 100);
INSERT INTO hosted.vaults (account_id, vault_id)
  VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb');
INSERT INTO hosted.vaults (account_id, vault_id)
  VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee');

DO $$
DECLARE
  v_account uuid := 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  v_vault uuid := 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
  v_other uuid := 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';
  v_old_reservation uuid := 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
  v_active uuid := 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
  v_ungranted uuid := 'ffffffff-ffff-4fff-8fff-ffffffffffff';
  v_snapshot uuid := '11111111-1111-4111-8111-111111111111';
  v_prefix text := 'accounts/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/vaults/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/';
  v_published text;
  v_new text;
  v_claims jsonb;
BEGIN
  v_published := v_prefix || 'metadata/' || v_snapshot || '.json';
  v_new := v_prefix || 'objects/aa/' || repeat('a', 62) || '.cvchunk';
  v_claims := jsonb_build_array(
    jsonb_build_object('key', v_published, 'bytes', 10,
      'sha256', repeat('a', 64)),
    jsonb_build_object('key', v_prefix || 'manifests/' || v_snapshot || '.cvmanifest',
      'bytes', 10, 'sha256', repeat('b', 64)),
    jsonb_build_object('key', v_prefix || 'refs/' || v_snapshot || '.json',
      'bytes', 10, 'sha256', repeat('c', 64))
  );
  IF NOT hosted.reserve_upload_current(v_account, v_vault, v_old_reservation,
      30, now() + interval '15 minutes', 100) OR
     NOT hosted.publish_verified_snapshot_current(v_account, v_vault,
      v_old_reservation, v_snapshot, v_claims, 100) OR
     NOT hosted.reserve_upload_current(v_account, v_vault, v_active,
      20, now() + interval '15 minutes', 100) THEN
    RAISE EXCEPTION 'fixture setup failed';
  END IF;
  IF NOT hosted.can_probe_upload_object_current(v_account, v_vault,
      v_active, v_published, 10, repeat('a', 64), 100) THEN
    RAISE EXCEPTION 'published object unavailable for exact HEAD';
  END IF;
  IF hosted.can_probe_upload_object_current(v_account, v_vault,
      v_active, v_new, 10, repeat('d', 64), 100) THEN
    RAISE EXCEPTION 'ungranted staged object probed';
  END IF;
  IF NOT hosted.reserve_object_grant_current(v_account, v_vault,
      v_active, v_new, 10, repeat('d', 64), 100) OR
     NOT hosted.can_probe_upload_object_current(v_account, v_vault,
      v_active, v_new, 10, repeat('d', 64), 100) THEN
    RAISE EXCEPTION 'granted upload could not be checked';
  END IF;
  IF NOT hosted.reserve_upload_current(v_account, v_vault, v_ungranted,
      10, now() + interval '15 minutes', 100) OR
     hosted.can_probe_upload_object_current(v_account, v_vault,
      v_ungranted, v_new, 10, repeat('d', 64), 100) THEN
    RAISE EXCEPTION 'one reservation could probe another staging ledger';
  END IF;
  IF hosted.can_probe_upload_object_current(v_account, v_vault,
      v_active, v_new, 11, repeat('d', 64), 100) OR
     hosted.can_probe_upload_object_current(v_account, v_vault,
      v_active, v_new, 10, repeat('e', 64), 100) OR
     hosted.can_probe_upload_object_current(v_account, v_other,
      v_active, v_new, 10, repeat('d', 64), 100) OR
     hosted.can_probe_upload_object_current(
      '99999999-9999-4999-8999-999999999999', v_vault,
      v_active, v_new, 10, repeat('d', 64), 100) OR
     hosted.can_probe_upload_object_current(v_account, v_vault,
      v_old_reservation, v_published, 10, repeat('a', 64), 100) OR
     hosted.can_probe_upload_object_current(v_account, v_vault,
      v_active, v_new, 10, repeat('d', 64), 40) THEN
    RAISE EXCEPTION 'conflicting, foreign, published, or over-quota probe';
  END IF;
  UPDATE hosted.upload_reservations SET expires_at = clock_timestamp() + interval '30 seconds'
    WHERE reservation_id = v_active;
  IF hosted.can_probe_upload_object_current(v_account, v_vault,
      v_active, v_new, 10, repeat('d', 64), 100) THEN
    RAISE EXCEPTION 'near-expiry probe allowed';
  END IF;
  UPDATE hosted.upload_reservations SET expires_at = clock_timestamp() + interval '5 minutes',
      state = 'cleanup_pending' WHERE reservation_id = v_active;
  IF hosted.can_probe_upload_object_current(v_account, v_vault,
      v_active, v_new, 10, repeat('d', 64), 100) THEN
    RAISE EXCEPTION 'cleanup probe allowed';
  END IF;
END;
$$;
ROLLBACK;
