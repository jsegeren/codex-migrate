-- Run only against a disposable PostgreSQL database after migrations 0000/0001.
BEGIN;
INSERT INTO hosted.accounts (account_id, allowance_bytes)
  VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 500);
INSERT INTO hosted.vaults (account_id, vault_id) VALUES
  ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'),
  ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'cccccccc-cccc-4ccc-8ccc-cccccccccccc');

CREATE FUNCTION pg_temp.fixture_objects(p_vault uuid, p_snapshot uuid,
  p_chunk_bytes bigint DEFAULT 100) RETURNS jsonb LANGUAGE sql AS $$
  SELECT jsonb_build_array(
    jsonb_build_object('key', 'accounts/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/vaults/' || p_vault ||
      '/metadata/' || p_snapshot || '.json', 'bytes', 10, 'sha256', repeat('a', 64)),
    jsonb_build_object('key', 'accounts/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/vaults/' || p_vault ||
      '/objects/' || repeat('b', 2) || '/' || repeat('b', 62) || '.cvchunk',
      'bytes', p_chunk_bytes, 'sha256', repeat('b', 64)),
    jsonb_build_object('key', 'accounts/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/vaults/' || p_vault ||
      '/manifests/' || p_snapshot || '.cvmanifest', 'bytes', 20, 'sha256', repeat('c', 64)),
    jsonb_build_object('key', 'accounts/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/vaults/' || p_vault ||
      '/refs/' || p_snapshot || '.json', 'bytes', 10, 'sha256', repeat('d', 64))
  );
$$;

DO $$
DECLARE
  v_account uuid := 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  v_vault uuid := 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
  v_other_vault uuid := 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
  v_first uuid := '11111111-1111-4111-8111-111111111111';
  v_second uuid := '22222222-2222-4222-8222-222222222222';
  v_third uuid := '33333333-3333-4333-8333-333333333333';
  v_first_reservation uuid := '44444444-4444-4444-8444-444444444444';
  v_second_reservation uuid := '55555555-5555-4555-8555-555555555555';
  v_third_reservation uuid := '66666666-6666-4666-8666-666666666666';
  v_failed_reservation uuid := '77777777-7777-4777-8777-777777777777';
  v_objects jsonb;
  v_bad jsonb;
  v_retained bigint;
  v_usage_events bigint[];
  v_reserved bigint;
  v_last uuid;
  v_message text;
  v_rejected boolean;
BEGIN
  v_objects := pg_temp.fixture_objects(v_vault, v_first);
  IF NOT hosted.reserve_upload(v_account, v_vault, v_first_reservation, 200,
      now() + interval '15 minutes') THEN RAISE EXCEPTION 'reservation failed'; END IF;
  IF NOT hosted.publish_verified_snapshot(v_account, v_vault,
      v_first_reservation, v_first, v_objects) THEN RAISE EXCEPTION 'publish failed'; END IF;
  SELECT retained_bytes, reserved_bytes INTO v_retained, v_reserved
    FROM hosted.accounts WHERE account_id = v_account;
  SELECT last_good_snapshot_id INTO v_last FROM hosted.vaults
    WHERE account_id = v_account AND vault_id = v_vault;
  IF v_retained <> 140 OR v_reserved <> 0 OR v_last <> v_first THEN
    RAISE EXCEPTION 'first publication counters or pointer wrong';
  END IF;
  SELECT array_agg(retained_bytes ORDER BY event_id) INTO v_usage_events
    FROM hosted.retained_usage_events WHERE account_id = v_account;
  IF v_usage_events <> ARRAY[0, 140]::bigint[] THEN
    RAISE EXCEPTION 'first publication usage event missing';
  END IF;

  -- An exact replay is idempotent; it may not change counters or the pointer.
  PERFORM hosted.publish_verified_snapshot(v_account, v_vault,
    v_first_reservation, v_first, v_objects);
  SELECT retained_bytes, reserved_bytes INTO v_retained, v_reserved
    FROM hosted.accounts WHERE account_id = v_account;
  IF v_retained <> 140 OR v_reserved <> 0 THEN RAISE EXCEPTION 'replay charged twice'; END IF;
  SELECT array_agg(retained_bytes ORDER BY event_id) INTO v_usage_events
    FROM hosted.retained_usage_events WHERE account_id = v_account;
  IF v_usage_events <> ARRAY[0, 140]::bigint[] THEN
    RAISE EXCEPTION 'publication replay changed storage usage';
  END IF;

  -- The next snapshot reuses one chunk; only its three new control objects
  -- consume storage. A retry of the older snapshot cannot roll it backward.
  IF NOT hosted.reserve_upload(v_account, v_vault, v_second_reservation, 50,
      now() + interval '15 minutes') THEN RAISE EXCEPTION 'second reserve failed'; END IF;
  PERFORM hosted.publish_verified_snapshot(v_account, v_vault,
    v_second_reservation, v_second, pg_temp.fixture_objects(v_vault, v_second));
  PERFORM hosted.publish_verified_snapshot(v_account, v_vault,
    v_first_reservation, v_first, v_objects);
  SELECT retained_bytes, reserved_bytes INTO v_retained, v_reserved
    FROM hosted.accounts WHERE account_id = v_account;
  SELECT last_good_snapshot_id INTO v_last FROM hosted.vaults
    WHERE account_id = v_account AND vault_id = v_vault;
  IF v_retained <> 180 OR v_reserved <> 0 OR v_last <> v_second THEN
    RAISE EXCEPTION 'reused chunk or retry pointer wrong';
  END IF;

  -- A second Mac has its own namespace and cannot reuse the first Mac's
  -- encrypted chunk, but both Vaults share the same account allowance.
  IF NOT hosted.reserve_upload(v_account, v_other_vault, v_third_reservation, 150,
      now() + interval '15 minutes') THEN RAISE EXCEPTION 'other Vault reserve failed'; END IF;
  PERFORM hosted.publish_verified_snapshot(v_account, v_other_vault,
    v_third_reservation, v_third, pg_temp.fixture_objects(v_other_vault, v_third));
  SELECT retained_bytes INTO v_retained FROM hosted.accounts WHERE account_id = v_account;
  IF v_retained <> 320 THEN RAISE EXCEPTION 'cross-Vault accounting wrong'; END IF;
  SELECT array_agg(retained_bytes ORDER BY event_id) INTO v_usage_events
    FROM hosted.retained_usage_events WHERE account_id = v_account;
  IF v_usage_events <> ARRAY[0, 140, 180, 320]::bigint[] THEN
    RAISE EXCEPTION 'cross-Vault storage usage history wrong';
  END IF;

  -- A conflicting replay must be refused without changing last good.
  v_bad := jsonb_set(v_objects, '{1,sha256}', to_jsonb(repeat('e', 64)));
  v_rejected := false;
  BEGIN
    PERFORM hosted.publish_verified_snapshot(v_account, v_vault,
      v_first_reservation, v_first, v_bad);
  EXCEPTION WHEN OTHERS THEN
    GET STACKED DIAGNOSTICS v_message = MESSAGE_TEXT;
    IF v_message !~ '^hosted_publication_' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'conflicting replay accepted'; END IF;

  IF NOT hosted.reserve_upload(v_account, v_vault, v_failed_reservation, 50,
      now() + interval '15 minutes') THEN RAISE EXCEPTION 'failed reserve failed'; END IF;
  -- This new snapshot would require 140 bytes but was granted only 50.
  v_rejected := false;
  BEGIN
    PERFORM hosted.publish_verified_snapshot(v_account, v_vault,
      v_failed_reservation, '88888888-8888-4888-8888-888888888888',
      jsonb_set(pg_temp.fixture_objects(v_vault,
        '88888888-8888-4888-8888-888888888888'),
        '{1,key}', to_jsonb('accounts/' || v_account || '/vaults/' || v_vault ||
          '/objects/' || repeat('f', 2) || '/' || repeat('f', 62) || '.cvchunk')));
  EXCEPTION WHEN OTHERS THEN
    GET STACKED DIAGNOSTICS v_message = MESSAGE_TEXT;
    IF v_message <> 'hosted_publication_over_quota' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'over-reservation publish accepted'; END IF;
  SELECT last_good_snapshot_id INTO v_last FROM hosted.vaults
    WHERE account_id = v_account AND vault_id = v_vault;
  IF v_last <> v_second OR EXISTS (SELECT 1 FROM hosted.snapshots
      WHERE snapshot_id = '88888888-8888-4888-8888-888888888888') THEN
    RAISE EXCEPTION 'failure moved pointer or left partial snapshot';
  END IF;
  SELECT state INTO v_message FROM hosted.upload_reservations
    WHERE reservation_id = v_failed_reservation;
  IF v_message <> 'active' THEN RAISE EXCEPTION 'failed reservation mutated'; END IF;

  -- The service may not publish objects under another account or Vault.
  v_rejected := false;
  BEGIN
    PERFORM hosted.publish_verified_snapshot(v_account, v_vault,
      v_failed_reservation, '99999999-9999-4999-8999-999999999999',
      pg_temp.fixture_objects(v_other_vault, '99999999-9999-4999-8999-999999999999'));
  EXCEPTION WHEN OTHERS THEN
    GET STACKED DIAGNOSTICS v_message = MESSAGE_TEXT;
    IF v_message <> 'hosted_publication_invalid' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'cross-Vault object accepted'; END IF;

  -- Required controls cannot be omitted, even if the remaining ciphertext
  -- objects fit the reservation.
  v_rejected := false;
  BEGIN
    PERFORM hosted.publish_verified_snapshot(v_account, v_vault,
      v_failed_reservation, '99999999-9999-4999-8999-999999999999',
      pg_temp.fixture_objects(v_vault,
        '99999999-9999-4999-8999-999999999999') - 0);
  EXCEPTION WHEN OTHERS THEN
    GET STACKED DIAGNOSTICS v_message = MESSAGE_TEXT;
    IF v_message <> 'hosted_publication_invalid' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'missing metadata accepted'; END IF;

  -- An existing immutable chunk cannot be relabelled with another digest.
  v_rejected := false;
  BEGIN
    PERFORM hosted.publish_verified_snapshot(v_account, v_vault,
      v_failed_reservation, '99999999-9999-4999-8999-999999999999',
      jsonb_set(pg_temp.fixture_objects(v_vault,
        '99999999-9999-4999-8999-999999999999'),
        '{1,sha256}', to_jsonb(repeat('e', 64))));
  EXCEPTION WHEN OTHERS THEN
    GET STACKED DIAGNOSTICS v_message = MESSAGE_TEXT;
    IF v_message <> 'hosted_publication_conflict' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'changed digest accepted'; END IF;

  SELECT retained_bytes, reserved_bytes INTO v_retained, v_reserved
    FROM hosted.accounts WHERE account_id = v_account;
  IF v_retained <> 320 OR v_reserved <> 50 THEN
    RAISE EXCEPTION 'failed publications changed account usage';
  END IF;

  -- An expired grant does not become publishable merely because its bytes
  -- remain reserved pending independently proven orphan cleanup.
  UPDATE hosted.upload_reservations SET
    created_at = clock_timestamp() - interval '2 hours',
    expires_at = clock_timestamp() - interval '1 hour'
    WHERE reservation_id = v_failed_reservation;
  v_rejected := false;
  BEGIN
    PERFORM hosted.publish_verified_snapshot(v_account, v_vault,
      v_failed_reservation, '99999999-9999-4999-8999-999999999999',
      pg_temp.fixture_objects(v_vault,
        '99999999-9999-4999-8999-999999999999'));
  EXCEPTION WHEN OTHERS THEN
    GET STACKED DIAGNOSTICS v_message = MESSAGE_TEXT;
    IF v_message <> 'hosted_publication_invalid' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'expired reservation published'; END IF;
END;
$$;
ROLLBACK;
