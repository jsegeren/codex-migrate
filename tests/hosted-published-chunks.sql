-- Disposable PostgreSQL only, after hosted migrations 0000-0023.
BEGIN;
DO $$
DECLARE
  v_account uuid := 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  v_vault uuid := 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
  v_other uuid := 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
  v_reservation uuid := 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
  v_snapshot uuid := 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';
  v_prefix text := 'accounts/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/vaults/' ||
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/';
  v_chunk text := repeat('b', 64);
  v_key text;
  v_objects jsonb;
  v_count integer;
  v_bytes bigint;
  v_digest text;
BEGIN
  INSERT INTO hosted.accounts (account_id, allowance_bytes)
    VALUES (v_account, 1000);
  INSERT INTO hosted.vaults (account_id, vault_id)
    VALUES (v_account, v_vault), (v_account, v_other);
  v_key := v_prefix || 'objects/bb/' || repeat('b', 62) || '.cvchunk';
  v_objects := jsonb_build_array(
    jsonb_build_object('key', v_prefix || 'metadata/' || v_snapshot || '.json',
      'bytes', 10, 'sha256', repeat('a', 64)),
    jsonb_build_object('key', v_key,
      'bytes', 20, 'sha256', repeat('c', 64)),
    jsonb_build_object('key', v_prefix || 'manifests/' || v_snapshot || '.cvmanifest',
      'bytes', 20, 'sha256', repeat('d', 64)),
    jsonb_build_object('key', v_prefix || 'refs/' || v_snapshot || '.json',
      'bytes', 10, 'sha256', repeat('e', 64)));
  IF NOT hosted.reserve_upload(v_account, v_vault, v_reservation, 100,
      clock_timestamp() + interval '15 minutes') THEN
    RAISE EXCEPTION 'reservation failed';
  END IF;
  IF NOT hosted.publish_verified_snapshot(v_account, v_vault,
      v_reservation, v_snapshot, v_objects) THEN
    RAISE EXCEPTION 'publication failed';
  END IF;
  SELECT count(*), max(bytes), max(sha256)
    INTO v_count, v_bytes, v_digest
    FROM hosted.published_chunk_candidates(v_account, v_vault,
      ARRAY[v_chunk, repeat('f', 64)]);
  IF v_count <> 1 OR v_bytes <> 20 OR v_digest <> repeat('c', 64) THEN
    RAISE EXCEPTION 'published exact chunk not found';
  END IF;
  SELECT count(*) INTO v_count
    FROM hosted.published_chunk_candidates(v_account, v_other,
      ARRAY[v_chunk]);
  IF v_count <> 0 THEN RAISE EXCEPTION 'foreign Vault chunk leaked'; END IF;
  INSERT INTO hosted.objects (account_id, vault_id, object_key, bytes, sha256)
    VALUES (v_account, v_vault,
      v_prefix || 'objects/ff/' || repeat('f', 62) || '.cvchunk',
      20, repeat('f', 64));
  SELECT count(*) INTO v_count
    FROM hosted.published_chunk_candidates(v_account, v_vault,
      ARRAY[repeat('f', 64)]);
  IF v_count <> 0 THEN RAISE EXCEPTION 'unpublished chunk leaked'; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_indexes
      WHERE schemaname = 'hosted' AND tablename = 'snapshot_objects'
        AND indexname = 'snapshot_objects_scoped_object_lookup') THEN
    RAISE EXCEPTION 'published lookup index missing';
  END IF;
END;
$$;
ROLLBACK;
