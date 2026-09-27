-- Disposable PostgreSQL only. A DELETE grant must name one expired,
-- exclusively claimed object and carry the database's issue time.
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
  v_reservation uuid := '11111111-1111-4111-8111-111111111111';
  v_key text := 'accounts/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/vaults/' ||
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/objects/aa/' ||
    repeat('a', 62) || '.cvchunk';
  v_bytes bigint;
  v_sha text;
  v_issued timestamptz;
BEGIN
  IF NOT hosted.reserve_upload_current(v_account, v_vault, v_reservation,
      100, clock_timestamp() + interval '30 minutes', 500) OR
     NOT hosted.reserve_object_grant_current(v_account, v_vault,
      v_reservation, v_key, 100, repeat('b', 64), 500) THEN
    RAISE EXCEPTION 'fixture reservation or grant failed';
  END IF;
  IF EXISTS (SELECT 1 FROM hosted.issue_cleanup_delete_grant(
      v_account, v_vault, v_reservation, v_key)) OR
     EXISTS (SELECT 1 FROM hosted.issue_cleanup_delete_grant(
      'dddddddd-dddd-4ddd-8ddd-dddddddddddd', v_vault,
      v_reservation, v_key)) THEN
    RAISE EXCEPTION 'active or foreign reservation received DELETE grant';
  END IF;
  UPDATE hosted.upload_reservations
    SET created_at = clock_timestamp() - interval '2 hours',
        expires_at = clock_timestamp() - interval '3 minutes'
    WHERE reservation_id = v_reservation;
  IF NOT hosted.claim_expired_upload_cleanup(v_reservation) THEN
    RAISE EXCEPTION 'cleanup quarantine failed';
  END IF;
  SELECT object_bytes, object_sha256, issued_at
    INTO v_bytes, v_sha, v_issued
    FROM hosted.issue_cleanup_delete_grant(v_account, v_vault,
      v_reservation, v_key);
  IF v_bytes <> 100 OR v_sha <> repeat('b', 64) OR
     v_issued IS NULL OR
     v_issued < clock_timestamp() - interval '5 seconds' OR
     v_issued > clock_timestamp() + interval '1 second' THEN
    RAISE EXCEPTION 'DELETE grant did not pin exact object and issue time';
  END IF;
  IF NOT hosted.record_cleanup_object_absent(v_account, v_vault,
      v_reservation, v_key, 100, repeat('b', 64)) OR
     EXISTS (SELECT 1 FROM hosted.issue_cleanup_delete_grant(
       v_account, v_vault, v_reservation, v_key)) THEN
    RAISE EXCEPTION 'deleted object received replayable DELETE grant';
  END IF;
END;
$$;
ROLLBACK;
