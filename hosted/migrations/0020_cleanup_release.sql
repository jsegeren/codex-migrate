-- The trusted cleanup worker must independently verify provider absence
-- before calling this function. SQL cannot turn a client claim or a DELETE
-- acknowledgement into proof that ciphertext is gone.
CREATE FUNCTION hosted.record_cleanup_object_absent(
  p_account_id uuid, p_vault_id uuid, p_reservation_id uuid,
  p_key text, p_bytes bigint, p_sha256 text
) RETURNS boolean LANGUAGE plpgsql AS $$
DECLARE
  v_reservation hosted.upload_reservations%ROWTYPE;
  v_claim hosted.cleanup_object_claims%ROWTYPE;
BEGIN
  IF p_account_id IS NULL OR p_vault_id IS NULL OR
     p_reservation_id IS NULL OR p_key IS NULL OR
     p_bytes IS NULL OR p_sha256 IS NULL THEN RETURN false; END IF;
  PERFORM 1 FROM hosted.accounts WHERE account_id = p_account_id FOR UPDATE;
  IF NOT FOUND THEN RETURN false; END IF;
  SELECT * INTO v_reservation FROM hosted.upload_reservations
    WHERE reservation_id = p_reservation_id AND account_id = p_account_id
      AND vault_id = p_vault_id FOR UPDATE;
  IF NOT FOUND OR v_reservation.state <> 'cleanup_pending' OR
     v_reservation.expires_at > clock_timestamp() - interval '2 minutes' THEN
    RETURN false;
  END IF;
  SELECT * INTO v_claim FROM hosted.cleanup_object_claims
    WHERE account_id = p_account_id AND vault_id = p_vault_id
      AND object_key = p_key AND reservation_id = p_reservation_id FOR UPDATE;
  IF NOT FOUND OR v_claim.object_bytes <> p_bytes OR
     v_claim.sha256 <> p_sha256 OR EXISTS (
       SELECT 1 FROM hosted.objects WHERE account_id = p_account_id
         AND vault_id = p_vault_id AND object_key = p_key
     ) OR EXISTS (
       SELECT 1 FROM hosted.upload_object_grants AS other_grant
       JOIN hosted.upload_reservations AS other_reservation
         USING (reservation_id)
       WHERE other_grant.object_key = p_key
         AND other_grant.reservation_id <> p_reservation_id
         AND other_reservation.account_id = p_account_id
         AND other_reservation.vault_id = p_vault_id
         AND other_reservation.expires_at > clock_timestamp() - interval '2 minutes'
     ) THEN RETURN false; END IF;
  IF v_claim.deleted_at IS NULL THEN
    UPDATE hosted.cleanup_object_claims SET deleted_at = clock_timestamp()
      WHERE account_id = p_account_id AND vault_id = p_vault_id
        AND object_key = p_key;
  END IF;
  RETURN true;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.record_cleanup_object_absent(
  uuid, uuid, uuid, text, bigint, text
) FROM PUBLIC;
--> statement-breakpoint
CREATE FUNCTION hosted.release_cleaned_upload_reservation(
  p_account_id uuid, p_vault_id uuid, p_reservation_id uuid
) RETURNS boolean LANGUAGE plpgsql AS $$
DECLARE
  v_reservation hosted.upload_reservations%ROWTYPE;
  v_reserved bigint;
BEGIN
  IF p_account_id IS NULL OR p_vault_id IS NULL OR
     p_reservation_id IS NULL THEN RETURN false; END IF;
  SELECT reserved_bytes INTO v_reserved FROM hosted.accounts
    WHERE account_id = p_account_id FOR UPDATE;
  IF NOT FOUND THEN RETURN false; END IF;
  SELECT * INTO v_reservation FROM hosted.upload_reservations
    WHERE reservation_id = p_reservation_id AND account_id = p_account_id
      AND vault_id = p_vault_id FOR UPDATE;
  IF NOT FOUND OR v_reservation.state <> 'cleanup_pending' OR
     v_reservation.expires_at > clock_timestamp() - interval '2 minutes' OR
     v_reserved < v_reservation.reserved_bytes THEN RETURN false; END IF;
  -- Published objects are already charged as retained bytes. Every other
  -- granted key needs an exact provider-absence record owned by this cleanup.
  -- Delay release for two minutes after the absence record so an earlier
  -- short-lived DELETE capability cannot replay against a new upload.
  IF EXISTS (
    SELECT 1 FROM hosted.upload_object_grants AS grant_row
    LEFT JOIN hosted.objects AS kept ON kept.account_id = p_account_id
      AND kept.vault_id = p_vault_id AND kept.object_key = grant_row.object_key
    LEFT JOIN hosted.cleanup_object_claims AS claim
      ON claim.account_id = p_account_id AND claim.vault_id = p_vault_id
      AND claim.object_key = grant_row.object_key
      AND claim.reservation_id = p_reservation_id
      AND claim.object_bytes = grant_row.object_bytes
      AND claim.sha256 = grant_row.sha256
    WHERE grant_row.reservation_id = p_reservation_id
      AND kept.object_key IS NULL
      AND (claim.deleted_at IS NULL OR
           claim.deleted_at > clock_timestamp() - interval '2 minutes')
  ) OR EXISTS (
    SELECT 1 FROM hosted.cleanup_object_claims
      WHERE reservation_id = p_reservation_id AND deleted_at IS NULL
  ) THEN RETURN false; END IF;

  UPDATE hosted.accounts SET reserved_bytes = reserved_bytes -
    v_reservation.reserved_bytes WHERE account_id = p_account_id;
  UPDATE hosted.upload_reservations SET state = 'released'
    WHERE reservation_id = p_reservation_id;
  DELETE FROM hosted.cleanup_object_claims
    WHERE reservation_id = p_reservation_id;
  RETURN true;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.release_cleaned_upload_reservation(
  uuid, uuid, uuid
) FROM PUBLIC;
