-- Ciphertext integrity and source completeness are separate claims. The
-- service cannot decrypt Codex history; this is the authenticated Mac's
-- source-reported status, not an independently verified content guarantee.
-- Historical publications remain unknown rather than being called complete.
ALTER TABLE hosted.snapshots ADD COLUMN source_coverage text NOT NULL
  DEFAULT 'unknown'
  CHECK (source_coverage IN ('unknown', 'complete', 'needs_attention'));
--> statement-breakpoint
CREATE INDEX snapshots_latest_source_complete_idx
  ON hosted.snapshots (account_id, vault_id, published_at DESC, snapshot_id DESC)
  WHERE source_coverage = 'complete';
--> statement-breakpoint
CREATE FUNCTION hosted.publish_checkpointed_staged_current(
  p_account_id uuid, p_vault_id uuid, p_reservation_id uuid,
  p_snapshot_id uuid, p_current_allowance bigint, p_source_coverage text
) RETURNS boolean LANGUAGE plpgsql AS $$
DECLARE
  v_published boolean;
  v_existing_coverage text;
BEGIN
  IF p_source_coverage NOT IN ('complete', 'needs_attention') OR
     p_source_coverage IS NULL THEN
    RAISE EXCEPTION 'hosted_source_coverage_invalid';
  END IF;
  -- Serialize with the existing publication path before checking whether
  -- this snapshot predates source-coverage attestation. Historical unknown
  -- snapshots must never be relabeled by a later device or retry.
  PERFORM 1 FROM hosted.accounts WHERE account_id = p_account_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'hosted_source_coverage_invalid'; END IF;
  SELECT source_coverage INTO v_existing_coverage FROM hosted.snapshots
    WHERE account_id = p_account_id AND vault_id = p_vault_id
      AND reservation_id = p_reservation_id AND snapshot_id = p_snapshot_id;
  IF FOUND AND v_existing_coverage <> p_source_coverage THEN
    RAISE EXCEPTION 'hosted_source_coverage_conflict';
  END IF;
  -- Both calls share one database transaction. A lost response retries the
  -- exact published snapshot; a conflicting classification cannot overwrite
  -- the first authenticated classification.
  v_published := hosted.publish_checkpointed_staged_current(
    p_account_id, p_vault_id, p_reservation_id, p_snapshot_id,
    p_current_allowance);
  IF NOT v_published THEN RETURN false; END IF;
  UPDATE hosted.snapshots SET source_coverage = p_source_coverage
    WHERE account_id = p_account_id AND vault_id = p_vault_id
      AND reservation_id = p_reservation_id AND snapshot_id = p_snapshot_id
      AND source_coverage IN ('unknown', p_source_coverage);
  IF NOT FOUND THEN RAISE EXCEPTION 'hosted_source_coverage_conflict'; END IF;
  RETURN true;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.publish_checkpointed_staged_current(
  uuid, uuid, uuid, uuid, bigint, text) FROM PUBLIC;
