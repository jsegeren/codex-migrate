-- Disposable PostgreSQL only, after hosted migrations 0000-0012.
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
  v_reservation uuid := 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
  v_key text := 'accounts/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/vaults/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/objects/aa/' || repeat('a', 62) || '.cvchunk';
BEGIN
  IF NOT hosted.reserve_upload_current(v_account, v_vault, v_reservation,
      20, now() + interval '15 minutes', 100) THEN
    RAISE EXCEPTION 'fixture reservation failed';
  END IF;
  IF hosted.classify_upload_object_current(v_account, v_vault, v_reservation,
      v_key, 10, repeat('a', 64), 100) IS DISTINCT FROM 'put' THEN
    RAISE EXCEPTION 'new object did not require reserved PUT';
  END IF;
  IF NOT hosted.reserve_object_grant_current(v_account, v_vault,
      v_reservation, v_key, 10, repeat('a', 64), 100) OR
     hosted.classify_upload_object_current(v_account, v_vault, v_reservation,
      v_key, 10, repeat('a', 64), 100) IS DISTINCT FROM 'head' THEN
    RAISE EXCEPTION 'PUT-granted object could not receive exact HEAD';
  END IF;
  IF hosted.classify_upload_object_current(v_account, v_vault, v_reservation,
      v_key, 10, repeat('a', 64), 10) IS NOT NULL OR
     hosted.classify_upload_object_current(v_account, v_vault,
      'ffffffff-ffff-4fff-8fff-ffffffffffff', v_key, 10,
      repeat('a', 64), 100) IS NOT NULL OR
     hosted.classify_upload_object_current(v_account,
      'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee', v_reservation,
      v_key, 10, repeat('a', 64), 100) IS NOT NULL OR
     hosted.classify_upload_object_current(v_account, v_vault,
      v_reservation, 'accounts/evil/vaults/evil/objects/aa/' || repeat('a', 62) || '.cvchunk',
      10, repeat('a', 64), 100) IS NOT NULL THEN
    RAISE EXCEPTION 'invalid authority became a PUT decision';
  END IF;
  UPDATE hosted.upload_reservations SET expires_at = clock_timestamp() + interval '30 seconds'
    WHERE reservation_id = v_reservation;
  IF hosted.classify_upload_object_current(v_account, v_vault, v_reservation,
      v_key, 10, repeat('a', 64), 100) IS NOT NULL THEN
    RAISE EXCEPTION 'near-expiry reservation became a decision';
  END IF;
END;
$$;
ROLLBACK;
