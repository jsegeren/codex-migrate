-- Query-only recovery-history proof on disposable CI PostgreSQL.
BEGIN;

INSERT INTO hosted.accounts (account_id, allowance_bytes) VALUES
  ('df000000-0000-4000-8000-000000000001', 1000);
INSERT INTO hosted.vaults (account_id, vault_id) VALUES
  ('df000000-0000-4000-8000-000000000001',
   'df000000-0000-4000-8000-000000000002');
INSERT INTO hosted.upload_reservations
  (reservation_id, account_id, vault_id, reserved_bytes, staged_bytes,
   expires_at, state) VALUES
  ('df000000-0000-4000-8000-000000000003',
   'df000000-0000-4000-8000-000000000001',
   'df000000-0000-4000-8000-000000000002', 30, 30,
   now() + interval '1 hour',
   'published'),
  ('df000000-0000-4000-8000-000000000004',
   'df000000-0000-4000-8000-000000000001',
   'df000000-0000-4000-8000-000000000002', 40, 40,
   now() + interval '1 hour',
   'published');
INSERT INTO hosted.snapshots
  (account_id, vault_id, snapshot_id, reservation_id,
   verified_object_count, published_at) VALUES
  ('df000000-0000-4000-8000-000000000001',
   'df000000-0000-4000-8000-000000000002',
   'df000000-0000-4000-8000-000000000005',
   'df000000-0000-4000-8000-000000000003', 3,
   '2026-09-28T20:00:00.123456Z'),
  ('df000000-0000-4000-8000-000000000001',
   'df000000-0000-4000-8000-000000000002',
   'df000000-0000-4000-8000-000000000006',
   'df000000-0000-4000-8000-000000000004', 4,
   '2026-09-28T20:00:00.123456Z');

PREPARE hosted_history(uuid, uuid, timestamptz, uuid) AS
SELECT s.snapshot_id,
  to_char(s.published_at AT TIME ZONE 'UTC',
    'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS published_at,
  s.verified_object_count, r.staged_bytes
FROM hosted.snapshots AS s
JOIN hosted.upload_reservations AS r ON r.reservation_id = s.reservation_id
WHERE s.account_id = $1::uuid AND s.vault_id = $2::uuid
  AND ($3::timestamptz IS NULL OR
    (s.published_at, s.snapshot_id) < ($3::timestamptz, $4::uuid))
ORDER BY s.published_at DESC, s.snapshot_id DESC LIMIT 51;

EXECUTE hosted_history('df000000-0000-4000-8000-000000000001',
  'df000000-0000-4000-8000-000000000002', NULL, NULL);
EXECUTE hosted_history('df000000-0000-4000-8000-000000000001',
  'df000000-0000-4000-8000-000000000002',
  '2026-09-28T20:00:00.123456Z',
  'df000000-0000-4000-8000-000000000006');

DO $$
DECLARE
  result_count int;
  observed text;
BEGIN
  SELECT count(*), min(to_char(s.published_at AT TIME ZONE 'UTC',
    'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'))
    INTO result_count, observed
    FROM hosted.snapshots AS s
    WHERE s.account_id = 'df000000-0000-4000-8000-000000000001'
      AND s.vault_id = 'df000000-0000-4000-8000-000000000002'
      AND (s.published_at, s.snapshot_id) <
        ('2026-09-28T20:00:00.123456Z'::timestamptz,
         'df000000-0000-4000-8000-000000000006'::uuid);
  IF result_count <> 1 OR observed <> '2026-09-28T20:00:00.123456Z' THEN
    RAISE EXCEPTION 'hosted history cursor lost an equal-time version';
  END IF;
END $$;

DO $$
DECLARE
  rejected boolean := false;
BEGIN
  IF EXISTS (SELECT 1 FROM hosted.snapshots WHERE source_coverage <> 'unknown'
      AND account_id = 'df000000-0000-4000-8000-000000000001') THEN
    RAISE EXCEPTION 'historical snapshot was incorrectly marked complete';
  END IF;
  BEGIN
    PERFORM hosted.publish_checkpointed_staged_current(
      'df000000-0000-4000-8000-000000000001',
      'df000000-0000-4000-8000-000000000002',
      'df000000-0000-4000-8000-000000000003',
      'df000000-0000-4000-8000-000000000005', 1000, 'complete');
  EXCEPTION WHEN OTHERS THEN rejected := true;
  END;
  IF NOT rejected OR EXISTS (SELECT 1 FROM hosted.snapshots
      WHERE account_id = 'df000000-0000-4000-8000-000000000001'
        AND source_coverage <> 'unknown') THEN
    RAISE EXCEPTION 'historical snapshot coverage was relabeled';
  END IF;
END $$;

DO $$
DECLARE
  selected uuid;
BEGIN
  -- A newer ciphertext-verified version may need attention; choose the
  -- newest source-reported complete version, not the vault pointer.
  UPDATE hosted.snapshots SET source_coverage = 'complete'
    WHERE snapshot_id = 'df000000-0000-4000-8000-000000000005';
  SELECT s.snapshot_id INTO selected FROM hosted.snapshots AS s
    JOIN hosted.upload_reservations AS r ON r.reservation_id = s.reservation_id
    WHERE s.account_id = 'df000000-0000-4000-8000-000000000001'
      AND s.vault_id = 'df000000-0000-4000-8000-000000000002'
      AND s.source_coverage = 'complete'
    ORDER BY s.published_at DESC, s.snapshot_id DESC LIMIT 1;
  IF selected <> 'df000000-0000-4000-8000-000000000005' THEN
    RAISE EXCEPTION 'latest complete snapshot selection failed';
  END IF;
END $$;

ROLLBACK;
