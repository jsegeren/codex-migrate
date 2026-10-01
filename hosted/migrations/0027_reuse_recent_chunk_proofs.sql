-- A ciphertext chunk in the latest published snapshot may carry its recent
-- provider proof into a later snapshot of the same account and Vault. Keep the
-- ORIGINAL proof time:
-- the 24-hour publication gate still requires a fresh R2 check when it ages.
-- Metadata, manifests, refs, unpublished objects, and changed facts never
-- qualify. This is a bounded optimization, not a new source of authority.
CREATE FUNCTION hosted.reuse_recent_published_chunk_proofs_current(
  p_account_id uuid,
  p_vault_id uuid,
  p_reservation_id uuid,
  p_snapshot_id uuid,
  p_current_allowance bigint
) RETURNS integer LANGUAGE plpgsql AS $$
DECLARE
  v_reservation hosted.upload_reservations%ROWTYPE;
  v_retained bigint;
  v_reserved bigint;
  v_candidates integer;
  v_recorded integer;
  v_prefix text := 'accounts/' || p_account_id || '/vaults/' || p_vault_id || '/';
BEGIN
  IF p_account_id IS NULL OR p_vault_id IS NULL OR p_reservation_id IS NULL OR
     p_snapshot_id IS NULL OR p_current_allowance IS NULL OR
     p_current_allowance <= 0 THEN
    RAISE EXCEPTION 'hosted_reused_proof_invalid';
  END IF;
  -- Match admission/publication lock order. A cleanup or another reservation
  -- cannot race the selection and insertion of these exact published facts.
  UPDATE hosted.accounts SET allowance_bytes = p_current_allowance
    WHERE account_id = p_account_id
    RETURNING retained_bytes, reserved_bytes INTO v_retained, v_reserved;
  IF NOT FOUND OR v_retained::numeric + v_reserved::numeric >
      p_current_allowance::numeric THEN
    RAISE EXCEPTION 'hosted_reused_proof_invalid';
  END IF;
  SELECT * INTO v_reservation FROM hosted.upload_reservations
    WHERE reservation_id = p_reservation_id AND account_id = p_account_id
      AND vault_id = p_vault_id FOR UPDATE;
  IF NOT FOUND OR v_reservation.state <> 'active' OR
     v_reservation.expires_at <= clock_timestamp() OR
     v_reservation.staged_snapshot_id <> p_snapshot_id OR
     v_reservation.declared_count IS NULL OR
     v_reservation.declared_count <> v_reservation.staged_count OR
     v_reservation.declared_bytes <> v_reservation.staged_bytes THEN
    RAISE EXCEPTION 'hosted_reused_proof_invalid';
  END IF;
  WITH candidates AS MATERIALIZED (
    SELECT staged.object_key, staged.object_bytes, staged.sha256,
      prior_proof.verified_at
    FROM hosted.staged_receipt_objects AS staged
    JOIN hosted.vaults AS vault
      ON vault.account_id = p_account_id AND vault.vault_id = p_vault_id
    JOIN hosted.snapshot_objects AS published_object
      ON published_object.account_id = p_account_id
      AND published_object.vault_id = p_vault_id
      AND published_object.snapshot_id = vault.last_good_snapshot_id
      AND published_object.object_key = staged.object_key
    JOIN hosted.snapshots AS published
      ON published.account_id = published_object.account_id
      AND published.vault_id = published_object.vault_id
      AND published.snapshot_id = published_object.snapshot_id
    JOIN hosted.upload_reservations AS prior_reservation
      ON prior_reservation.reservation_id = published.reservation_id
      AND prior_reservation.state = 'published'
    JOIN hosted.verified_receipt_objects AS prior_proof
      ON prior_proof.reservation_id = published.reservation_id
      AND prior_proof.object_key = staged.object_key
      AND prior_proof.object_bytes = staged.object_bytes
      AND prior_proof.sha256 = staged.sha256
    LEFT JOIN hosted.verified_receipt_objects AS current_proof
      ON current_proof.reservation_id = p_reservation_id
      AND current_proof.object_key = staged.object_key
    WHERE staged.reservation_id = p_reservation_id
      AND left(staged.object_key, length(v_prefix)) = v_prefix
      AND substring(staged.object_key FROM length(v_prefix) + 1)
        ~ '^objects/[0-9a-f]{2}/[0-9a-f]{62}\.cvchunk$'
      AND prior_proof.verified_at >= clock_timestamp() - interval '24 hours'
      AND (current_proof.object_key IS NULL OR
        current_proof.verified_at < clock_timestamp() - interval '24 hours')
    ORDER BY staged.object_key LIMIT 2048
  ), recorded AS (
    INSERT INTO hosted.verified_receipt_objects
      (reservation_id, object_key, object_bytes, sha256, verified_at)
      SELECT p_reservation_id, object_key, object_bytes, sha256, verified_at
        FROM candidates
      ON CONFLICT (reservation_id, object_key) DO UPDATE SET
        verified_at = EXCLUDED.verified_at
      WHERE hosted.verified_receipt_objects.object_bytes = EXCLUDED.object_bytes
        AND hosted.verified_receipt_objects.sha256 = EXCLUDED.sha256
        AND hosted.verified_receipt_objects.verified_at < EXCLUDED.verified_at
      RETURNING 1
  ) SELECT (SELECT count(*) FROM candidates), (SELECT count(*) FROM recorded)
      INTO v_candidates, v_recorded;
  IF v_candidates <> v_recorded THEN
    RAISE EXCEPTION 'hosted_reused_proof_conflict';
  END IF;
  RETURN v_recorded;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.reuse_recent_published_chunk_proofs_current(
  uuid, uuid, uuid, uuid, bigint) FROM PUBLIC;
