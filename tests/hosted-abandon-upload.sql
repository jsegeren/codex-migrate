-- Disposable PostgreSQL only. Abandoning an upload quarantines its grant;
-- it neither releases quota nor authorizes deletion without provider proof.
BEGIN;
INSERT INTO hosted.accounts (account_id, allowance_bytes)
  VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 1000);
INSERT INTO hosted.vaults (account_id, vault_id)
  VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb');

DO $$
DECLARE
  v_account uuid := 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  v_vault uuid := 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
  v_reservation uuid := '11111111-1111-4111-8111-111111111111';
  v_key text := 'accounts/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/vaults/' ||
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/objects/aa/' || repeat('a', 62) || '.cvchunk';
  v_state text;
  v_reserved bigint;
  v_expiry timestamptz;
BEGIN
  IF NOT hosted.reserve_upload_current(v_account, v_vault, v_reservation,
      100, clock_timestamp() + interval '30 minutes', 1000) OR
     NOT hosted.reserve_object_grant_current(v_account, v_vault, v_reservation,
      v_key, 100, repeat('b', 64), 1000) THEN
    RAISE EXCEPTION 'fixture reservation or grant failed';
  END IF;
  IF hosted.abandon_upload_reservation(v_account, v_vault,
       '22222222-2222-4222-8222-222222222222') OR
     hosted.abandon_upload_reservation(v_account,
       '33333333-3333-4333-8333-333333333333', v_reservation) OR
     hosted.abandon_upload_reservation(NULL, v_vault, v_reservation) THEN
    RAISE EXCEPTION 'foreign reservation was abandoned';
  END IF;
  IF NOT hosted.abandon_upload_reservation(v_account, v_vault, v_reservation)
     OR NOT hosted.abandon_upload_reservation(v_account, v_vault, v_reservation) THEN
    RAISE EXCEPTION 'owned abandon or idempotent retry failed';
  END IF;
  SELECT state, expires_at INTO v_state, v_expiry
    FROM hosted.upload_reservations WHERE reservation_id = v_reservation;
  SELECT reserved_bytes INTO v_reserved FROM hosted.accounts
    WHERE account_id = v_account;
  IF v_state <> 'cleanup_pending' OR v_expiry > clock_timestamp() OR
     v_reserved <> 100 THEN
    RAISE EXCEPTION 'abandon released quota or did not quarantine';
  END IF;
  IF hosted.renew_upload_reservation_current(v_account, v_vault, v_reservation,
       clock_timestamp() + interval '55 minutes', 1000) OR
     hosted.reserve_object_grant_current(v_account, v_vault, v_reservation,
       v_key, 100, repeat('b', 64), 1000) OR
     hosted.claim_expired_upload_cleanup(v_reservation) OR
     hosted.release_cleaned_upload_reservation(v_account, v_vault, v_reservation) THEN
    RAISE EXCEPTION 'abandoned upload accepted new work or premature cleanup';
  END IF;
  UPDATE hosted.upload_reservations
    SET created_at = clock_timestamp() - interval '2 hours',
        expires_at = clock_timestamp() - interval '3 minutes'
    WHERE reservation_id = v_reservation;
  IF NOT hosted.claim_expired_upload_cleanup(v_reservation) OR
     hosted.release_cleaned_upload_reservation(v_account, v_vault, v_reservation) THEN
    RAISE EXCEPTION 'unverified object was released after quarantine';
  END IF;
  UPDATE hosted.upload_reservations SET state = 'published'
    WHERE reservation_id = v_reservation;
  IF hosted.abandon_upload_reservation(v_account, v_vault, v_reservation) THEN
    RAISE EXCEPTION 'published upload was converted into an orphan';
  END IF;
END;
$$;
ROLLBACK;
