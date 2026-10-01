-- Disposable PostgreSQL only. Claim is a quarantine, never quota release.
BEGIN;
INSERT INTO hosted.accounts (account_id, allowance_bytes)
  VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 500);
INSERT INTO hosted.vaults (account_id, vault_id)
  VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb');

DO $$
DECLARE
  v_account uuid := 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  v_vault uuid := 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
  v_early uuid := '11111111-1111-4111-8111-111111111111';
  v_expired uuid := '22222222-2222-4222-8222-222222222222';
  v_bytes bigint;
  v_state text;
BEGIN
  IF hosted.claim_expired_upload_cleanup(NULL) OR
     hosted.claim_expired_upload_cleanup(
       '33333333-3333-4333-8333-333333333333') THEN
    RAISE EXCEPTION 'unknown reservation was claimed';
  END IF;
  IF NOT hosted.reserve_upload_current(v_account, v_vault, v_early,
      100, clock_timestamp() + interval '30 minutes', 500) OR
     NOT hosted.reserve_upload_current(v_account, v_vault, v_expired,
      200, clock_timestamp() + interval '30 minutes', 500) THEN
    RAISE EXCEPTION 'fixture reservation failed';
  END IF;
  IF hosted.claim_expired_upload_cleanup(v_early) THEN
    RAISE EXCEPTION 'active reservation was claimed';
  END IF;
  UPDATE hosted.upload_reservations
    SET created_at = clock_timestamp() - interval '2 hours',
        expires_at = clock_timestamp() - interval '90 seconds'
    WHERE reservation_id = v_early;
  IF hosted.claim_expired_upload_cleanup(v_early) THEN
    RAISE EXCEPTION 'unexpired storage token window was claimed';
  END IF;
  UPDATE hosted.upload_reservations
    SET created_at = clock_timestamp() - interval '2 hours',
        expires_at = clock_timestamp() - interval '3 minutes'
    WHERE reservation_id = v_expired;
  IF NOT hosted.claim_expired_upload_cleanup(v_expired) OR
     NOT hosted.claim_expired_upload_cleanup(v_expired) THEN
    RAISE EXCEPTION 'expired claim or idempotent retry failed';
  END IF;
  SELECT state INTO v_state FROM hosted.upload_reservations
    WHERE reservation_id = v_expired;
  SELECT reserved_bytes INTO v_bytes FROM hosted.accounts
    WHERE account_id = v_account;
  IF v_state <> 'cleanup_pending' OR v_bytes <> 300 THEN
    RAISE EXCEPTION 'claim changed quota or did not quarantine';
  END IF;
  IF hosted.renew_upload_reservation_current(v_account, v_vault, v_expired,
      clock_timestamp() + interval '55 minutes', 500) THEN
    RAISE EXCEPTION 'quarantined reservation renewed';
  END IF;
  IF hosted.claim_expired_upload_cleanup(v_early) THEN
    RAISE EXCEPTION 'different reservation was claimed';
  END IF;
  UPDATE hosted.upload_reservations SET state = 'released',
      expires_at = clock_timestamp() - interval '3 minutes'
    WHERE reservation_id = v_early;
  IF hosted.claim_expired_upload_cleanup(v_early) THEN
    RAISE EXCEPTION 'released reservation was reclaimed';
  END IF;
  UPDATE hosted.upload_reservations SET state = 'published'
    WHERE reservation_id = v_early;
  IF hosted.claim_expired_upload_cleanup(v_early) THEN
    RAISE EXCEPTION 'published reservation was reclaimed';
  END IF;
END;
$$;
ROLLBACK;
