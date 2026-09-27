-- Disposable PostgreSQL only. A deletion claim cannot become data loss or a
-- quota release, and it excludes racing PUT grants and publication.
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
  v_old uuid := '11111111-1111-4111-8111-111111111111';
  v_live uuid := '22222222-2222-4222-8222-222222222222';
  v_new uuid := '33333333-3333-4333-8333-333333333333';
  v_prefix text := 'accounts/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/vaults/' ||
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/objects/aa/';
  v_orphan text := v_prefix || repeat('a', 62) || '.cvchunk';
  v_shared text := v_prefix || repeat('b', 62) || '.cvchunk';
  v_published text := v_prefix || repeat('c', 62) || '.cvchunk';
  v_sha text := repeat('d', 64);
  v_reserved bigint;
  v_rejected boolean;
  v_elastic_allowed boolean;
BEGIN
  IF NOT hosted.reserve_upload_current(v_account, v_vault, v_old,
      300, clock_timestamp() + interval '30 minutes', 1000) OR
     NOT hosted.reserve_upload_current(v_account, v_vault, v_live,
      200, clock_timestamp() + interval '30 minutes', 1000) OR
     NOT hosted.reserve_upload_current(v_account, v_vault, v_new,
      100, clock_timestamp() + interval '30 minutes', 1000) THEN
    RAISE EXCEPTION 'fixture reservation failed';
  END IF;
  IF NOT hosted.reserve_object_grant_current(v_account, v_vault, v_old,
      v_orphan, 100, v_sha, 1000) OR
     NOT hosted.reserve_object_grant_current(v_account, v_vault, v_old,
      v_shared, 100, v_sha, 1000) OR
     NOT hosted.reserve_object_grant_current(v_account, v_vault, v_old,
      v_published, 100, v_sha, 1000) OR
     NOT hosted.reserve_object_grant_current(v_account, v_vault, v_live,
      v_shared, 100, v_sha, 1000) THEN
    RAISE EXCEPTION 'fixture object grant failed';
  END IF;
  INSERT INTO hosted.objects (account_id, vault_id, object_key, bytes, sha256)
    VALUES (v_account, v_vault, v_published, 100, v_sha);
  IF hosted.claim_expired_upload_object(v_account, v_vault, v_old, v_orphan) THEN
    RAISE EXCEPTION 'active reservation claimed an object';
  END IF;
  UPDATE hosted.upload_reservations
    SET created_at = clock_timestamp() - interval '2 hours',
        expires_at = clock_timestamp() - interval '3 minutes'
    WHERE reservation_id = v_old;
  IF NOT hosted.claim_expired_upload_cleanup(v_old) THEN
    RAISE EXCEPTION 'fixture cleanup quarantine failed';
  END IF;
  IF NOT hosted.claim_expired_upload_object(v_account, v_vault, v_old,
      v_orphan) OR
     NOT hosted.claim_expired_upload_object(v_account, v_vault, v_old,
      v_orphan) THEN
    RAISE EXCEPTION 'exclusive orphan claim or retry failed';
  END IF;
  IF hosted.claim_expired_upload_object(v_account, v_vault, v_old,
      v_shared) OR
     hosted.claim_expired_upload_object(v_account, v_vault, v_old,
      v_published) OR
     hosted.claim_expired_upload_object(v_account, v_vault, v_old,
      v_prefix || repeat('e', 62) || '.cvchunk') OR
     hosted.claim_expired_upload_object(v_account, v_vault, v_live,
      v_orphan) THEN
    RAISE EXCEPTION 'shared, published, ungranted or foreign key was claimed';
  END IF;
  IF hosted.reserve_object_grant_current(v_account, v_vault, v_new,
      v_orphan, 100, v_sha, 1000) THEN
    RAISE EXCEPTION 'claimed key received a direct PUT grant';
  END IF;
  v_elastic_allowed := false;
  BEGIN
    v_elastic_allowed := hosted.reserve_object_grant_elastic_current(
      v_account, v_vault, v_new, v_orphan, 100, v_sha, 1000);
  EXCEPTION WHEN raise_exception THEN
    IF SQLERRM <> 'hosted_elastic_grant_failed' THEN RAISE; END IF;
    v_elastic_allowed := false;
  END;
  IF v_elastic_allowed THEN
    RAISE EXCEPTION 'claimed key received a new PUT grant';
  END IF;
  v_rejected := false;
  BEGIN
    INSERT INTO hosted.objects (account_id, vault_id, object_key, bytes, sha256)
      VALUES (v_account, v_vault, v_orphan, 100, v_sha);
  EXCEPTION WHEN raise_exception THEN
    IF SQLERRM <> 'hosted_cleanup_object_claimed' THEN RAISE; END IF;
    v_rejected := true;
  END;
  IF NOT v_rejected THEN RAISE EXCEPTION 'claimed object was published'; END IF;
  SELECT reserved_bytes INTO v_reserved FROM hosted.accounts
    WHERE account_id = v_account;
  IF v_reserved <> 600 THEN
    RAISE EXCEPTION 'object claim changed reserved capacity';
  END IF;
  UPDATE hosted.upload_reservations
    SET created_at = clock_timestamp() - interval '2 hours',
        expires_at = clock_timestamp() - interval '3 minutes'
    WHERE reservation_id = v_live;
  IF NOT hosted.claim_expired_upload_object(v_account, v_vault, v_old,
      v_shared) THEN
    RAISE EXCEPTION 'old shared grant remained permanently blocked';
  END IF;
  IF (SELECT count(*) FROM hosted.cleanup_object_claims
      WHERE account_id = v_account) <> 2 THEN
    RAISE EXCEPTION 'unexpected cleanup claim count';
  END IF;
END;
$$;
ROLLBACK;
