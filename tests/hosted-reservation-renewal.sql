-- Disposable PostgreSQL only, after hosted migrations 0000-0010.
BEGIN;
INSERT INTO hosted.accounts (account_id, allowance_bytes)
  VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 500);
INSERT INTO hosted.vaults (account_id, vault_id)
  VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb');
INSERT INTO hosted.vaults (account_id, vault_id)
  VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'cccccccc-cccc-4ccc-8ccc-cccccccccccc');

DO $$
DECLARE
  v_account uuid := 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  v_vault uuid := 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
  v_other uuid := 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
  v_reservation uuid := 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
  v_expiry timestamptz;
  v_allowance bigint;
BEGIN
  IF NOT hosted.reserve_upload_current(v_account, v_vault, v_reservation,
      200, now() + interval '15 minutes', 500) THEN
    RAISE EXCEPTION 'fixture reservation failed';
  END IF;
  IF NOT hosted.renew_upload_reservation_current(v_account, v_vault,
      v_reservation, clock_timestamp() + interval '55 minutes', 500) THEN
    RAISE EXCEPTION 'valid renewal failed';
  END IF;
  SELECT expires_at INTO v_expiry FROM hosted.upload_reservations
    WHERE reservation_id = v_reservation;
  IF v_expiry < clock_timestamp() + interval '54 minutes' THEN
    RAISE EXCEPTION 'renewal did not extend expiry';
  END IF;
  IF hosted.renew_upload_reservation_current(v_account, v_other,
      v_reservation, clock_timestamp() + interval '56 minutes', 100) OR
     hosted.renew_upload_reservation_current(
      'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee', v_vault,
      v_reservation, clock_timestamp() + interval '56 minutes', 100) THEN
    RAISE EXCEPTION 'foreign reservation renewed';
  END IF;
  SELECT allowance_bytes INTO v_allowance FROM hosted.accounts
    WHERE account_id = v_account;
  IF v_allowance <> 500 THEN RAISE EXCEPTION 'foreign renewal mutated quota'; END IF;

  IF hosted.renew_upload_reservation_current(v_account, v_vault,
      v_reservation, clock_timestamp() + interval '61 minutes', 500) OR
     hosted.renew_upload_reservation_current(v_account, v_vault,
      v_reservation, clock_timestamp() + interval '1 minute', 500) THEN
    RAISE EXCEPTION 'invalid renewal duration accepted';
  END IF;
  IF hosted.renew_upload_reservation_current(v_account, v_vault,
      v_reservation, clock_timestamp() + interval '56 minutes', 150) THEN
    RAISE EXCEPTION 'downgraded over-quota renewal accepted';
  END IF;
  SELECT expires_at, allowance_bytes INTO v_expiry, v_allowance
    FROM hosted.upload_reservations JOIN hosted.accounts USING (account_id)
    WHERE reservation_id = v_reservation;
  IF v_expiry < clock_timestamp() + interval '54 minutes' OR v_allowance <> 150 THEN
    RAISE EXCEPTION 'downgrade changed expiry or failed to record allowance';
  END IF;
  UPDATE hosted.upload_reservations SET created_at = clock_timestamp() - interval '2 hours',
      expires_at = clock_timestamp() - interval '1 minute'
    WHERE reservation_id = v_reservation;
  IF hosted.renew_upload_reservation_current(v_account, v_vault,
      v_reservation, clock_timestamp() + interval '55 minutes', 500) THEN
    RAISE EXCEPTION 'expired reservation revived';
  END IF;
  UPDATE hosted.upload_reservations SET expires_at = clock_timestamp() + interval '5 minutes',
      state = 'cleanup_pending' WHERE reservation_id = v_reservation;
  IF hosted.renew_upload_reservation_current(v_account, v_vault,
      v_reservation, clock_timestamp() + interval '55 minutes', 500) THEN
    RAISE EXCEPTION 'cleanup reservation revived';
  END IF;
END;
$$;
ROLLBACK;
