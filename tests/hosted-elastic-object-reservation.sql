-- Disposable PostgreSQL only, after hosted migrations 0000-0014.
BEGIN;
INSERT INTO hosted.accounts (account_id, allowance_bytes, retained_bytes)
  VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 100, 90);
INSERT INTO hosted.vaults (account_id, vault_id)
  VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb');

DO $$
DECLARE
  v_account uuid := 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  v_vault uuid := 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
  v_reservation uuid := 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
  v_first text := 'accounts/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/vaults/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/metadata/11111111-1111-4111-8111-111111111111.json';
  v_second text := 'accounts/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/vaults/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/refs/11111111-1111-4111-8111-111111111111.json';
  v_third text := 'accounts/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/vaults/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/manifests/11111111-1111-4111-8111-111111111111.cvmanifest';
  v_reserved bigint;
  v_granted bigint;
  v_account_reserved bigint;
BEGIN
  IF NOT hosted.reserve_upload_current(v_account, v_vault, v_reservation,
      1, now() + interval '15 minutes', 100) THEN
    RAISE EXCEPTION 'tiny incremental reservation failed';
  END IF;
  IF NOT hosted.reserve_object_grant_elastic_current(v_account, v_vault,
      v_reservation, v_first, 4, repeat('a', 64), 100) OR
     NOT hosted.reserve_object_grant_elastic_current(v_account, v_vault,
      v_reservation, v_first, 4, repeat('a', 64), 100) OR
     NOT hosted.reserve_object_grant_elastic_current(v_account, v_vault,
      v_reservation, v_second, 6, repeat('b', 64), 100) THEN
    RAISE EXCEPTION 'exact growth or idempotent retry failed';
  END IF;
  SELECT reserved_bytes, granted_bytes INTO v_reserved, v_granted
    FROM hosted.upload_reservations WHERE reservation_id = v_reservation;
  SELECT reserved_bytes INTO v_account_reserved FROM hosted.accounts
    WHERE account_id = v_account;
  IF (v_reserved, v_granted, v_account_reserved) <> (10, 10, 10) OR
     (SELECT count(*) FROM hosted.upload_object_grants
       WHERE reservation_id = v_reservation) <> 2 THEN
    RAISE EXCEPTION 'growth did not charge distinct bytes exactly once';
  END IF;

  IF hosted.reserve_object_grant_elastic_current(v_account, v_vault,
      v_reservation, v_third, 1, repeat('c', 64), 100) OR
     hosted.reserve_object_grant_elastic_current(v_account, v_vault,
      v_reservation, v_first, 4, repeat('d', 64), 100) OR
     hosted.reserve_object_grant_elastic_current(v_account, v_vault,
      v_reservation, replace(v_third, v_vault::text,
        'dddddddd-dddd-4ddd-8ddd-dddddddddddd'), 1, repeat('c', 64), 100) THEN
    RAISE EXCEPTION 'over-quota, conflicting, or foreign grant passed';
  END IF;
  SELECT reserved_bytes, granted_bytes INTO v_reserved, v_granted
    FROM hosted.upload_reservations WHERE reservation_id = v_reservation;
  IF (v_reserved, v_granted) <> (10, 10) THEN
    RAISE EXCEPTION 'denied grant changed quota';
  END IF;
  IF hosted.reserve_object_grant_elastic_current(v_account, v_vault,
      v_reservation, v_first, 4, repeat('a', 64), 99) THEN
    RAISE EXCEPTION 'downgraded allowance reused a grant';
  END IF;
  UPDATE hosted.upload_reservations SET expires_at = now() + interval '30 seconds'
    WHERE reservation_id = v_reservation;
  IF hosted.reserve_object_grant_elastic_current(v_account, v_vault,
      v_reservation, v_first, 4, repeat('a', 64), 100) THEN
    RAISE EXCEPTION 'near-expiry reservation reused a grant';
  END IF;
END;
$$;
ROLLBACK;
