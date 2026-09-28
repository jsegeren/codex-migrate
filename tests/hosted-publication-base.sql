-- Disposable PostgreSQL: overlapping uploads may proceed, but a stale one
-- cannot silently replace the latest verified history. Other Vaults remain
-- independent, and an exact old retry cannot roll last-good backward.
BEGIN;
INSERT INTO hosted.accounts (account_id, allowance_bytes)
  VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 500);
INSERT INTO hosted.vaults (account_id, vault_id) VALUES
  ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
   'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'),
  ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
   'cccccccc-cccc-4ccc-8ccc-cccccccccccc');

CREATE FUNCTION pg_temp.fixture_objects(p_vault uuid, p_snapshot uuid)
RETURNS jsonb LANGUAGE sql AS $$
  SELECT jsonb_build_array(
    jsonb_build_object('key', 'accounts/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/vaults/' ||
      p_vault || '/metadata/' || p_snapshot || '.json',
      'bytes', 10, 'sha256', repeat('a', 64)),
    jsonb_build_object('key', 'accounts/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/vaults/' ||
      p_vault || '/manifests/' || p_snapshot || '.cvmanifest',
      'bytes', 10, 'sha256', repeat('b', 64)),
    jsonb_build_object('key', 'accounts/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/vaults/' ||
      p_vault || '/refs/' || p_snapshot || '.json',
      'bytes', 10, 'sha256', repeat('c', 64)));
$$;

DO $$
DECLARE
  v_account uuid := 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  v_vault uuid := 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
  v_other_vault uuid := 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
  v_first_reservation uuid := '11111111-1111-4111-8111-111111111111';
  v_stale_reservation uuid := '22222222-2222-4222-8222-222222222222';
  v_next_reservation uuid := '33333333-3333-4333-8333-333333333333';
  v_other_reservation uuid := '44444444-4444-4444-8444-444444444444';
  v_first uuid := '55555555-5555-4555-8555-555555555555';
  v_stale uuid := '66666666-6666-4666-8666-666666666666';
  v_next uuid := '77777777-7777-4777-8777-777777777777';
  v_other uuid := '88888888-8888-4888-8888-888888888888';
  v_last uuid;
  v_rejected boolean;
  v_error text;
BEGIN
  IF NOT hosted.reserve_upload(v_account, v_vault, v_first_reservation,
      30, clock_timestamp() + interval '15 minutes') OR
     NOT hosted.reserve_upload(v_account, v_vault, v_stale_reservation,
      30, clock_timestamp() + interval '15 minutes') OR
     NOT hosted.reserve_upload(v_account, v_other_vault, v_other_reservation,
      30, clock_timestamp() + interval '15 minutes') THEN
    RAISE EXCEPTION 'overlapping reservation fixture failed';
  END IF;
  IF EXISTS (SELECT 1 FROM hosted.upload_reservations
      WHERE reservation_id IN (v_first_reservation, v_stale_reservation,
                               v_other_reservation)
        AND base_snapshot_id IS NOT NULL) THEN
    RAISE EXCEPTION 'first-generation base was not empty';
  END IF;
  PERFORM hosted.publish_verified_snapshot(v_account, v_vault,
    v_first_reservation, v_first, pg_temp.fixture_objects(v_vault, v_first));
  v_rejected := false;
  BEGIN
    PERFORM hosted.publish_verified_snapshot(v_account, v_vault,
      v_stale_reservation, v_stale, pg_temp.fixture_objects(v_vault, v_stale));
  EXCEPTION WHEN OTHERS THEN
    GET STACKED DIAGNOSTICS v_error = MESSAGE_TEXT;
    IF v_error <> 'hosted_publication_base_changed' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected OR EXISTS (SELECT 1 FROM hosted.snapshots
      WHERE account_id = v_account AND vault_id = v_vault
        AND snapshot_id = v_stale) THEN
    RAISE EXCEPTION 'stale publication was accepted or partly committed';
  END IF;
  SELECT last_good_snapshot_id INTO v_last FROM hosted.vaults
    WHERE account_id = v_account AND vault_id = v_vault;
  IF v_last <> v_first THEN
    RAISE EXCEPTION 'stale publication moved last-good';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM hosted.accounts
      WHERE account_id = v_account AND retained_bytes = 30
        AND reserved_bytes = 60) THEN
    RAISE EXCEPTION 'stale publication altered quota accounting';
  END IF;

  -- An independent Mac/Vault can publish while this Vault has stale work.
  PERFORM hosted.publish_verified_snapshot(v_account, v_other_vault,
    v_other_reservation, v_other, pg_temp.fixture_objects(v_other_vault, v_other));
  IF NOT hosted.reserve_upload(v_account, v_vault, v_next_reservation,
      30, clock_timestamp() + interval '15 minutes') OR
     (SELECT base_snapshot_id FROM hosted.upload_reservations
      WHERE reservation_id = v_next_reservation) <> v_first THEN
    RAISE EXCEPTION 'new reservation did not capture current last-good';
  END IF;
  PERFORM hosted.publish_verified_snapshot(v_account, v_vault,
    v_next_reservation, v_next, pg_temp.fixture_objects(v_vault, v_next));
  PERFORM hosted.publish_verified_snapshot(v_account, v_vault,
    v_first_reservation, v_first, pg_temp.fixture_objects(v_vault, v_first));
  SELECT last_good_snapshot_id INTO v_last FROM hosted.vaults
    WHERE account_id = v_account AND vault_id = v_vault;
  IF v_last <> v_next THEN
    RAISE EXCEPTION 'old retry rolled back current last-good';
  END IF;
END;
$$;
ROLLBACK;
