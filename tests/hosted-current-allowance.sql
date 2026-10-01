-- Disposable PostgreSQL only, after hosted migrations 0000-0006.
BEGIN;
INSERT INTO hosted.accounts (account_id, allowance_bytes)
  VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 500);
INSERT INTO hosted.vaults (account_id, vault_id)
  VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb');

CREATE FUNCTION pg_temp.fixture_objects(p_snapshot uuid) RETURNS jsonb
LANGUAGE sql AS $$
  SELECT jsonb_build_array(
    jsonb_build_object('key', 'accounts/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/vaults/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/metadata/' || p_snapshot || '.json',
      'bytes', 10, 'sha256', repeat('a', 64)),
    jsonb_build_object('key', 'accounts/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/vaults/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/objects/' || repeat('b', 2) || '/' || repeat('b', 62) || '.cvchunk',
      'bytes', 100, 'sha256', repeat('b', 64)),
    jsonb_build_object('key', 'accounts/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/vaults/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/manifests/' || p_snapshot || '.cvmanifest',
      'bytes', 20, 'sha256', repeat('c', 64)),
    jsonb_build_object('key', 'accounts/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/vaults/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/refs/' || p_snapshot || '.json',
      'bytes', 10, 'sha256', repeat('d', 64))
  );
$$;

DO $$
DECLARE
  v_account uuid := 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  v_vault uuid := 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
  v_first uuid := '11111111-1111-4111-8111-111111111111';
  v_second uuid := '22222222-2222-4222-8222-222222222222';
  v_first_reservation uuid := '33333333-3333-4333-8333-333333333333';
  v_second_reservation uuid := '44444444-4444-4444-8444-444444444444';
  v_rejected boolean := false;
  v_message text;
  v_retained bigint;
  v_reserved bigint;
  v_allowance bigint;
  v_last uuid;
BEGIN
  IF NOT hosted.reserve_upload_current(v_account, v_vault,
      v_first_reservation, 200, now() + interval '15 minutes', 500) THEN
    RAISE EXCEPTION 'fresh allowance rejected first reservation';
  END IF;
  PERFORM hosted.publish_verified_snapshot_current(v_account, v_vault,
    v_first_reservation, v_first, pg_temp.fixture_objects(v_first), 500);
  IF NOT hosted.reserve_upload_current(v_account, v_vault,
      v_second_reservation, 50, now() + interval '15 minutes', 500) THEN
    RAISE EXCEPTION 'fresh allowance rejected second reservation';
  END IF;

  -- The second snapshot has already reserved bytes at the old price. A
  -- downgrade before publication must not use that stale account allowance.
  BEGIN
    PERFORM hosted.publish_verified_snapshot_current(v_account, v_vault,
      v_second_reservation, v_second, pg_temp.fixture_objects(v_second), 150);
  EXCEPTION WHEN OTHERS THEN
    GET STACKED DIAGNOSTICS v_message = MESSAGE_TEXT;
    IF v_message <> 'hosted_publication_over_quota' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'downgraded publish was accepted'; END IF;
  SELECT retained_bytes, reserved_bytes, allowance_bytes
    INTO v_retained, v_reserved, v_allowance
    FROM hosted.accounts WHERE account_id = v_account;
  SELECT last_good_snapshot_id INTO v_last FROM hosted.vaults
    WHERE account_id = v_account AND vault_id = v_vault;
  IF v_retained <> 140 OR v_reserved <> 50 OR v_last <> v_first OR
     EXISTS (SELECT 1 FROM hosted.snapshots WHERE snapshot_id = v_second) THEN
    RAISE EXCEPTION 'failed downgrade changed last-good state';
  END IF;

  IF hosted.reserve_upload_current(v_account, v_vault,
      '55555555-5555-4555-8555-555555555555', 1,
      now() + interval '15 minutes', 150) THEN
    RAISE EXCEPTION 'downgraded account reserved new bytes';
  END IF;
  SELECT allowance_bytes INTO v_allowance FROM hosted.accounts
    WHERE account_id = v_account;
  IF v_allowance <> 150 THEN RAISE EXCEPTION 'fresh allowance was not recorded'; END IF;
  IF hosted.reserve_upload_current(v_account,
      '99999999-9999-4999-8999-999999999999',
      '66666666-6666-4666-8666-666666666666', 1,
      now() + interval '15 minutes', 300) THEN
    RAISE EXCEPTION 'foreign Vault reserved bytes';
  END IF;
  SELECT allowance_bytes INTO v_allowance FROM hosted.accounts
    WHERE account_id = v_account;
  IF v_allowance <> 150 THEN RAISE EXCEPTION 'foreign Vault changed allowance'; END IF;

  -- A later, freshly verified allowance can safely publish the same frozen
  -- receipt without recreating or double-charging the reservation.
  PERFORM hosted.publish_verified_snapshot_current(v_account, v_vault,
    v_second_reservation, v_second, pg_temp.fixture_objects(v_second), 200);
  SELECT retained_bytes, reserved_bytes, allowance_bytes
    INTO v_retained, v_reserved, v_allowance
    FROM hosted.accounts WHERE account_id = v_account;
  SELECT last_good_snapshot_id INTO v_last FROM hosted.vaults
    WHERE account_id = v_account AND vault_id = v_vault;
  IF v_retained <> 180 OR v_reserved <> 0 OR v_allowance <> 200 OR
     v_last <> v_second THEN RAISE EXCEPTION 'fresh allowance publication drift'; END IF;
END;
$$;
ROLLBACK;
