-- Server-only: claim the exact stale key and return a DB-issued timestamp for
-- one short-lived method-bound DELETE capability. The signer must use this
-- timestamp, not a later wall clock, so a delayed signer cannot create a
-- token that outlives the two-minute claim-release hold.
CREATE FUNCTION hosted.issue_cleanup_delete_grant(
  p_account_id uuid, p_vault_id uuid, p_reservation_id uuid, p_key text
) RETURNS TABLE (object_bytes bigint, object_sha256 text,
                 issued_at timestamptz) LANGUAGE plpgsql AS $$
BEGIN
  IF NOT hosted.claim_expired_upload_object(p_account_id, p_vault_id,
      p_reservation_id, p_key) THEN RETURN; END IF;
  RETURN QUERY SELECT claim.object_bytes, claim.sha256, clock_timestamp()
    FROM hosted.cleanup_object_claims AS claim
    WHERE claim.account_id = p_account_id AND claim.vault_id = p_vault_id
      AND claim.reservation_id = p_reservation_id
      AND claim.object_key = p_key AND claim.deleted_at IS NULL;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.issue_cleanup_delete_grant(
  uuid, uuid, uuid, text
) FROM PUBLIC;
