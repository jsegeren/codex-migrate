-- Classify one exact object under a still-active reservation. "put" is only
-- a decision to request a separate quota-recorded PUT grant; it is never a
-- storage capability. Invalid authority returns NULL, never "put".
CREATE FUNCTION hosted.classify_upload_object_current(
  p_account_id uuid,
  p_vault_id uuid,
  p_reservation_id uuid,
  p_key text,
  p_bytes bigint,
  p_sha256 text,
  p_current_allowance bigint
) RETURNS text LANGUAGE sql VOLATILE AS $$
  SELECT CASE WHEN EXISTS (
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
      AND length(p_key) <= 300
      AND p_bytes > 0 AND p_bytes <= 100000000
      AND p_sha256 ~ '^[0-9a-f]{64}$'
  ) THEN CASE WHEN hosted.can_probe_upload_object_current(
      p_account_id, p_vault_id, p_reservation_id,
      p_key, p_bytes, p_sha256, p_current_allowance
    ) THEN 'head' ELSE 'put' END ELSE NULL END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.classify_upload_object_current(
  uuid, uuid, uuid, text, bigint, text, bigint
) FROM PUBLIC;
