-- A HEAD grant may verify an immutable object already published in this Vault
-- or an exact object previously granted under this same active reservation.
-- It never grants a read, cross-Vault probe, or probe for an unrecorded upload.
CREATE FUNCTION hosted.can_probe_upload_object_current(
  p_account_id uuid,
  p_vault_id uuid,
  p_reservation_id uuid,
  p_key text,
  p_bytes bigint,
  p_sha256 text,
  p_current_allowance bigint
) RETURNS boolean LANGUAGE sql VOLATILE AS $$
  SELECT EXISTS (
    SELECT 1 FROM hosted.upload_reservations AS r
    JOIN hosted.accounts AS a ON a.account_id = r.account_id
    WHERE r.account_id = p_account_id AND r.vault_id = p_vault_id
      AND r.reservation_id = p_reservation_id AND r.state = 'active'
      AND r.expires_at > clock_timestamp() + interval '1 minute'
      AND p_current_allowance > 0
      AND a.retained_bytes::numeric + a.reserved_bytes::numeric <=
        p_current_allowance::numeric
      AND p_key LIKE 'accounts/' || p_account_id::text || '/vaults/' ||
        p_vault_id::text || '/%'
      AND p_bytes > 0 AND p_bytes <= 100000000
      AND p_sha256 ~ '^[0-9a-f]{64}$'
      AND (
        EXISTS (
          SELECT 1 FROM hosted.snapshot_objects AS so
          JOIN hosted.objects AS o USING (account_id, vault_id, object_key)
          WHERE so.account_id = r.account_id AND so.vault_id = r.vault_id
            AND so.object_key = p_key AND o.bytes = p_bytes
            AND o.sha256 = p_sha256
        ) OR EXISTS (
          SELECT 1 FROM hosted.upload_object_grants AS g
          WHERE g.reservation_id = r.reservation_id
            AND g.object_key = p_key AND g.object_bytes = p_bytes
            AND g.sha256 = p_sha256
        )
      )
  );
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.can_probe_upload_object_current(
  uuid, uuid, uuid, text, bigint, text, bigint
) FROM PUBLIC;
