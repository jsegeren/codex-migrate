-- Daily snapshots repeat most chunk IDs. Lookup must be indexed by scoped
-- object key, not scan every historical snapshot for each candidate chunk.
CREATE INDEX snapshot_objects_scoped_object_lookup
  ON hosted.snapshot_objects (account_id, vault_id, object_key);
--> statement-breakpoint
CREATE FUNCTION hosted.published_chunk_candidates(
  p_account_id uuid, p_vault_id uuid, p_ids text[]
) RETURNS TABLE (id text, bytes bigint, sha256 text)
LANGUAGE sql STABLE AS $$
  WITH candidates AS (
    SELECT DISTINCT unnest(p_ids) AS id
  )
  SELECT c.id, o.bytes, o.sha256
  FROM candidates AS c
  JOIN hosted.objects AS o
    ON o.account_id = p_account_id AND o.vault_id = p_vault_id
      AND o.object_key = 'accounts/' || p_account_id::text || '/vaults/' ||
        p_vault_id::text || '/objects/' || left(c.id, 2) || '/' ||
        substr(c.id, 3) || '.cvchunk'
  WHERE EXISTS (
    SELECT 1 FROM hosted.snapshot_objects AS so
    WHERE so.account_id = o.account_id AND so.vault_id = o.vault_id
      AND so.object_key = o.object_key
  )
  ORDER BY c.id;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.published_chunk_candidates(uuid, uuid, text[])
  FROM PUBLIC;
