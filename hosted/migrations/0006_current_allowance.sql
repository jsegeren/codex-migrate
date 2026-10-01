-- The service passes the allowance it just checked against the current
-- Stripe Subscription, never one supplied by the device. Lock and update the
-- account row in the same transaction as reservation/publication so an older
-- stored allowance cannot authorize new bytes after a downgrade.
CREATE FUNCTION hosted.reserve_upload_current(
  p_account_id uuid,
  p_vault_id uuid,
  p_reservation_id uuid,
  p_bytes bigint,
  p_expires_at timestamptz,
  p_current_allowance bigint
) RETURNS boolean LANGUAGE plpgsql AS $$
BEGIN
  IF p_current_allowance IS NULL OR p_current_allowance <= 0 THEN
    RETURN false;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM hosted.vaults
      WHERE account_id = p_account_id AND vault_id = p_vault_id) THEN
    RETURN false;
  END IF;
  UPDATE hosted.accounts SET allowance_bytes = p_current_allowance
    WHERE account_id = p_account_id;
  IF NOT FOUND THEN RETURN false; END IF;
  RETURN hosted.reserve_upload(p_account_id, p_vault_id, p_reservation_id,
    p_bytes, p_expires_at);
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.reserve_upload_current(
  uuid, uuid, uuid, bigint, timestamptz, bigint
) FROM PUBLIC;
--> statement-breakpoint
CREATE FUNCTION hosted.publish_verified_snapshot_current(
  p_account_id uuid,
  p_vault_id uuid,
  p_reservation_id uuid,
  p_snapshot_id uuid,
  p_verified_objects jsonb,
  p_current_allowance bigint
) RETURNS boolean LANGUAGE plpgsql AS $$
BEGIN
  IF p_current_allowance IS NULL OR p_current_allowance <= 0 THEN
    RAISE EXCEPTION 'hosted_publication_invalid';
  END IF;
  UPDATE hosted.accounts SET allowance_bytes = p_current_allowance
    WHERE account_id = p_account_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'hosted_publication_invalid'; END IF;
  RETURN hosted.publish_verified_snapshot(p_account_id, p_vault_id,
    p_reservation_id, p_snapshot_id, p_verified_objects);
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.publish_verified_snapshot_current(
  uuid, uuid, uuid, uuid, jsonb, bigint
) FROM PUBLIC;
