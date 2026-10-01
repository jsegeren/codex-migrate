-- The first emailed-code claim creates the buyer account, first Mac Vault,
-- and hashed device session in one transaction. No subscription or capacity
-- is granted here. A separate, authenticated second-device flow is required.
DROP FUNCTION hosted.claim_purchase_enrollment(text, text, text, uuid);
--> statement-breakpoint
CREATE FUNCTION hosted.claim_and_pair_first_device(
  p_challenge_hash text,
  p_session_id text,
  p_mode text,
  p_account_id uuid,
  p_vault_id uuid,
  p_device_id uuid,
  p_device_token_hash text
) RETURNS uuid LANGUAGE plpgsql AS $$
BEGIN
  IF p_account_id IS NULL OR p_vault_id IS NULL OR p_device_id IS NULL OR
     p_device_token_hash IS NULL OR
     p_device_token_hash !~ '^[0-9a-f]{64}$' OR
     p_challenge_hash IS NULL OR p_session_id IS NULL OR p_mode IS NULL OR
     p_mode NOT IN ('sandbox', 'live') THEN RETURN NULL; END IF;
  UPDATE hosted.enrollment_challenges SET consumed_at = clock_timestamp()
    WHERE challenge_hash = p_challenge_hash
      AND purchase_session_id = p_session_id AND purchase_mode = p_mode
      AND mail_state = 'sent' AND consumed_at IS NULL
      AND expires_at > clock_timestamp();
  IF NOT FOUND THEN RETURN NULL; END IF;

  INSERT INTO hosted.accounts (account_id, allowance_bytes)
    VALUES (p_account_id, 0);
  INSERT INTO hosted.purchase_enrollments
    (account_id, purchase_session_id, purchase_mode)
    VALUES (p_account_id, p_session_id, p_mode);
  INSERT INTO hosted.vaults (account_id, vault_id)
    VALUES (p_account_id, p_vault_id);
  INSERT INTO hosted.device_sessions
    (token_hash, account_id, vault_id, device_id, expires_at)
    VALUES (p_device_token_hash, p_account_id, p_vault_id,
      p_device_id, now() + interval '29 days');
  RETURN p_account_id;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.claim_and_pair_first_device(
  text, text, text, uuid, uuid, uuid, text
) FROM PUBLIC;
