-- Disposable PostgreSQL only. This tests database accounting after a trusted
-- worker has proved provider absence; it does not itself prove R2 deletion.
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
  v_old uuid := '11111111-1111-4111-8111-111111111111';
  v_empty uuid := '22222222-2222-4222-8222-222222222222';
  v_key text := 'accounts/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/vaults/' ||
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/objects/aa/' ||
    repeat('a', 62) || '.cvchunk';
  v_sha text := repeat('b', 64);
  v_first timestamptz;
  v_second timestamptz;
  v_reserved bigint;
  v_state text;
BEGIN
  IF NOT hosted.reserve_upload_current(v_account, v_vault, v_old,
      200, clock_timestamp() + interval '30 minutes', 500) OR
     NOT hosted.reserve_upload_current(v_account, v_vault, v_empty,
      1, clock_timestamp() + interval '30 minutes', 500) OR
     NOT hosted.reserve_object_grant_current(v_account, v_vault, v_old,
      v_key, 100, v_sha, 500) THEN
    RAISE EXCEPTION 'fixture reservation or grant failed';
  END IF;
  IF hosted.release_cleaned_upload_reservation(v_account, v_vault, v_old) OR
     hosted.record_cleanup_object_absent(v_account, v_vault, v_old,
       v_key, 100, v_sha) THEN
    RAISE EXCEPTION 'active reservation was cleaned';
  END IF;
  UPDATE hosted.upload_reservations
    SET created_at = clock_timestamp() - interval '2 hours',
        expires_at = clock_timestamp() - interval '3 minutes'
    WHERE reservation_id IN (v_old, v_empty);
  IF NOT hosted.claim_expired_upload_cleanup(v_old) OR
     NOT hosted.claim_expired_upload_cleanup(v_empty) OR
     NOT hosted.claim_expired_upload_object(v_account, v_vault, v_old, v_key) THEN
    RAISE EXCEPTION 'fixture cleanup claim failed';
  END IF;
  IF hosted.release_cleaned_upload_reservation(v_account, v_vault, v_old) OR
     hosted.record_cleanup_object_absent(v_account, v_vault, v_old,
       v_key, 100, repeat('c', 64)) OR
     hosted.record_cleanup_object_absent(v_account, v_vault, v_empty,
       v_key, 100, v_sha) THEN
    RAISE EXCEPTION 'unverified or foreign object was cleared';
  END IF;
  IF NOT hosted.record_cleanup_object_absent(v_account, v_vault, v_old,
      v_key, 100, v_sha) THEN
    RAISE EXCEPTION 'trusted absence record failed';
  END IF;
  SELECT deleted_at INTO v_first FROM hosted.cleanup_object_claims
    WHERE account_id = v_account AND vault_id = v_vault AND object_key = v_key;
  IF v_first IS NULL OR
     NOT hosted.record_cleanup_object_absent(v_account, v_vault, v_old,
       v_key, 100, v_sha) THEN
    RAISE EXCEPTION 'absence retry failed';
  END IF;
  SELECT deleted_at INTO v_second FROM hosted.cleanup_object_claims
    WHERE account_id = v_account AND vault_id = v_vault AND object_key = v_key;
  IF v_second <> v_first OR
     hosted.release_cleaned_upload_reservation(v_account, v_vault, v_old) THEN
    RAISE EXCEPTION 'absence retry changed the replay window';
  END IF;
  -- Simulate the two-minute capability drain without sleeping in CI.
  UPDATE hosted.cleanup_object_claims
    SET claimed_at = clock_timestamp() - interval '4 minutes',
        deleted_at = clock_timestamp() - interval '3 minutes'
    WHERE account_id = v_account AND vault_id = v_vault AND object_key = v_key;
  IF NOT hosted.release_cleaned_upload_reservation(v_account, v_vault, v_old) OR
     hosted.release_cleaned_upload_reservation(v_account, v_vault, v_old) OR
     NOT hosted.release_cleaned_upload_reservation(v_account, v_vault, v_empty) THEN
    RAISE EXCEPTION 'cleaned reservation did not release exactly once';
  END IF;
  SELECT reserved_bytes INTO v_reserved FROM hosted.accounts
    WHERE account_id = v_account;
  SELECT state INTO v_state FROM hosted.upload_reservations
    WHERE reservation_id = v_old;
  IF v_reserved <> 0 OR v_state <> 'released' OR
     EXISTS (SELECT 1 FROM hosted.cleanup_object_claims
       WHERE reservation_id = v_old) THEN
    RAISE EXCEPTION 'release did not clear exact quota and claim';
  END IF;
END;
$$;
ROLLBACK;
