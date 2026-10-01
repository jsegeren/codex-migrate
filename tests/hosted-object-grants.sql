-- Disposable PostgreSQL only, after hosted migrations 0000-0007.
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
  v_key text := 'accounts/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/vaults/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/metadata/11111111-1111-4111-8111-111111111111.json';
  v_second text := 'accounts/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/vaults/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/refs/11111111-1111-4111-8111-111111111111.json';
  v_bytes bigint;
  v_count integer;
BEGIN
  IF NOT hosted.reserve_upload_current(v_account, v_vault, v_reservation,
      30, now() + interval '15 minutes', 100) THEN
    RAISE EXCEPTION 'fixture reservation failed';
  END IF;
  IF NOT hosted.reserve_object_grant_current(v_account, v_vault,
      v_reservation, v_key, 10, repeat('a', 64), 100) THEN
    RAISE EXCEPTION 'first grant failed';
  END IF;
  IF NOT hosted.reserve_object_grant_current(v_account, v_vault,
      v_reservation, v_key, 10, repeat('a', 64), 100) THEN
    RAISE EXCEPTION 'idempotent grant failed';
  END IF;
  IF hosted.reserve_object_grant_current(v_account, v_vault,
      v_reservation, v_key, 10, repeat('b', 64), 100) OR
     hosted.reserve_object_grant_current(v_account, v_vault,
      v_reservation, v_second, 21, repeat('b', 64), 100) OR
     hosted.reserve_object_grant_current(v_account, v_vault,
      v_reservation, replace(v_second, 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
        'dddddddd-dddd-4ddd-8ddd-dddddddddddd'), 1, repeat('b', 64), 100) OR
     hosted.reserve_object_grant_current(v_account, v_vault,
      v_reservation, '../escape', 1, repeat('b', 64), 100) THEN
    RAISE EXCEPTION 'conflicting, excessive, or foreign grant was issued';
  END IF;
  IF NOT hosted.reserve_object_grant_current(v_account, v_vault,
      v_reservation, v_second, 20, repeat('b', 64), 100) THEN
    RAISE EXCEPTION 'within-reservation grant failed';
  END IF;
  SELECT granted_bytes, granted_objects INTO v_bytes, v_count
    FROM hosted.upload_reservations WHERE reservation_id = v_reservation;
  IF v_bytes <> 30 OR v_count <> 2 OR
     (SELECT count(*) FROM hosted.upload_object_grants
       WHERE reservation_id = v_reservation) <> 2 THEN
    RAISE EXCEPTION 'grants consumed reservation incorrectly';
  END IF;

  -- A fresh downgrade blocks even an idempotent grant. Never issue another
  -- capability from a stale subscription allowance.
  IF hosted.reserve_object_grant_current(v_account, v_vault,
      v_reservation, v_key, 10, repeat('a', 64), 20) THEN
    RAISE EXCEPTION 'downgraded account granted upload';
  END IF;
  UPDATE hosted.upload_reservations SET expires_at = now() + interval '30 seconds'
    WHERE reservation_id = v_reservation;
  IF hosted.reserve_object_grant_current(v_account, v_vault,
      v_reservation, v_key, 10, repeat('a', 64), 100) THEN
    RAISE EXCEPTION 'near-expiry reservation granted upload';
  END IF;
  UPDATE hosted.upload_reservations SET
      created_at = now() - interval '2 hours',
      expires_at = now() - interval '1 hour'
    WHERE reservation_id = v_reservation;
  IF hosted.reserve_object_grant_current(v_account, v_vault,
      v_reservation, v_key, 10, repeat('a', 64), 100) THEN
    RAISE EXCEPTION 'expired reservation granted upload';
  END IF;
END;
$$;
ROLLBACK;
