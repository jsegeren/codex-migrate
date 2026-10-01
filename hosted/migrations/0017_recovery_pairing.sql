-- A lost Mac must not make its published ciphertext unreachable. A fresh,
-- purchase-verified email challenge may pair a new device to one *existing*
-- Vault. It never creates an account/Vault, starts a trial, changes capacity,
-- decrypts content, or revokes another device. The native client must still
-- import the separately saved Vault recovery key to read the ciphertext.
CREATE TABLE hosted.recovery_challenges (
  purchase_session_id text NOT NULL,
  purchase_mode text NOT NULL,
  challenge_hash text NOT NULL UNIQUE CHECK (challenge_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  mail_state text NOT NULL DEFAULT 'pending'
    CHECK (mail_state IN ('pending', 'sent', 'rejected', 'uncertain')),
  consumed_at timestamptz,
  window_started_at timestamptz NOT NULL,
  requests_in_window integer NOT NULL CHECK (requests_in_window BETWEEN 1 AND 5),
  PRIMARY KEY (purchase_session_id, purchase_mode),
  FOREIGN KEY (purchase_session_id, purchase_mode)
    REFERENCES commerce_purchases (session_id, mode),
  CHECK (expires_at > created_at AND expires_at <= created_at + interval '10 minutes'),
  CHECK (consumed_at IS NULL OR consumed_at >= created_at)
);
--> statement-breakpoint
CREATE FUNCTION hosted.issue_recovery_challenge(
  p_session_id text, p_mode text, p_hash text
) RETURNS boolean LANGUAGE plpgsql AS $$
DECLARE
  v_issued timestamptz := clock_timestamp();
  v_count integer;
BEGIN
  IF p_session_id IS NULL OR p_mode IS NULL OR
     p_mode NOT IN ('sandbox', 'live') OR
     p_hash IS NULL OR p_hash !~ '^[0-9a-f]{64}$' OR
     NOT EXISTS (SELECT 1 FROM hosted.purchase_enrollments
       WHERE purchase_session_id = p_session_id AND purchase_mode = p_mode) THEN
    RETURN false;
  END IF;
  INSERT INTO hosted.recovery_challenges
    (purchase_session_id, purchase_mode, challenge_hash, created_at,
      expires_at, window_started_at, requests_in_window)
    VALUES (p_session_id, p_mode, p_hash, v_issued,
      v_issued + interval '10 minutes', v_issued, 1)
    ON CONFLICT (purchase_session_id, purchase_mode) DO UPDATE
      SET challenge_hash = excluded.challenge_hash,
          created_at = excluded.created_at,
          expires_at = excluded.expires_at,
          mail_state = 'pending',
          consumed_at = NULL,
          window_started_at = CASE
            WHEN hosted.recovery_challenges.window_started_at <=
              v_issued - interval '1 day' THEN v_issued
            ELSE hosted.recovery_challenges.window_started_at END,
          requests_in_window = CASE
            WHEN hosted.recovery_challenges.window_started_at <=
              v_issued - interval '1 day' THEN 1
            ELSE hosted.recovery_challenges.requests_in_window + 1 END
      WHERE hosted.recovery_challenges.created_at <=
          v_issued - interval '10 minutes'
        AND (hosted.recovery_challenges.window_started_at <=
          v_issued - interval '1 day' OR
          hosted.recovery_challenges.requests_in_window < 5)
        AND EXISTS (SELECT 1 FROM hosted.purchase_enrollments
          WHERE purchase_session_id = p_session_id AND purchase_mode = p_mode)
    RETURNING requests_in_window INTO v_count;
  RETURN FOUND;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.issue_recovery_challenge(text, text, text)
  FROM PUBLIC;
--> statement-breakpoint
CREATE FUNCTION hosted.record_recovery_challenge_delivery(
  p_hash text, p_state text
) RETURNS boolean LANGUAGE plpgsql AS $$
BEGIN
  IF p_hash IS NULL OR p_state NOT IN ('sent', 'rejected', 'uncertain') THEN
    RETURN false;
  END IF;
  UPDATE hosted.recovery_challenges SET mail_state = p_state
    WHERE challenge_hash = p_hash AND mail_state = 'pending'
      AND expires_at > clock_timestamp();
  RETURN FOUND;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.record_recovery_challenge_delivery(text, text)
  FROM PUBLIC;
--> statement-breakpoint
CREATE FUNCTION hosted.list_recovery_vaults(
  p_hash text, p_session_id text, p_mode text
) RETURNS TABLE(vault_id uuid, published_at timestamptz)
LANGUAGE plpgsql AS $$
BEGIN
  IF p_hash IS NULL OR p_session_id IS NULL OR p_mode IS NULL OR
     NOT EXISTS (SELECT 1 FROM hosted.recovery_challenges AS challenge
       WHERE challenge.challenge_hash = p_hash
         AND challenge.purchase_session_id = p_session_id
         AND challenge.purchase_mode = p_mode
         AND challenge.mail_state = 'sent'
         AND challenge.consumed_at IS NULL
         AND challenge.expires_at > clock_timestamp()) THEN
    RETURN;
  END IF;
  RETURN QUERY SELECT vault.vault_id, snapshot.published_at
    FROM hosted.purchase_enrollments AS purchase
    JOIN hosted.vaults AS vault ON vault.account_id = purchase.account_id
    LEFT JOIN hosted.snapshots AS snapshot
      ON snapshot.account_id = vault.account_id
        AND snapshot.vault_id = vault.vault_id
        AND snapshot.snapshot_id = vault.last_good_snapshot_id
    WHERE purchase.purchase_session_id = p_session_id
      AND purchase.purchase_mode = p_mode
    ORDER BY snapshot.published_at DESC NULLS LAST, vault.vault_id;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.list_recovery_vaults(text, text, text)
  FROM PUBLIC;
--> statement-breakpoint
CREATE FUNCTION hosted.claim_recovery_vault_device(
  p_hash text, p_session_id text, p_mode text,
  p_vault_id uuid, p_device_id uuid, p_device_token_hash text
) RETURNS uuid LANGUAGE plpgsql AS $$
DECLARE
  v_account uuid;
BEGIN
  IF p_hash IS NULL OR p_session_id IS NULL OR p_mode IS NULL OR
     p_vault_id IS NULL OR p_device_id IS NULL OR
     p_device_token_hash IS NULL OR
     p_device_token_hash !~ '^[0-9a-f]{64}$' THEN RETURN NULL; END IF;
  SELECT account_id INTO v_account FROM hosted.purchase_enrollments
    WHERE purchase_session_id = p_session_id AND purchase_mode = p_mode;
  IF v_account IS NULL THEN RETURN NULL; END IF;
  -- Serialize device-count and Vault membership checks with other account
  -- mutations. A code can be used once, for only one Vault.
  PERFORM 1 FROM hosted.accounts WHERE account_id = v_account FOR UPDATE;
  IF NOT FOUND OR NOT EXISTS (SELECT 1 FROM hosted.vaults
      WHERE account_id = v_account AND vault_id = p_vault_id) OR
     (SELECT count(*) FROM hosted.device_sessions
      WHERE account_id = v_account AND vault_id = p_vault_id
        AND revoked_at IS NULL AND expires_at > clock_timestamp()) >= 16 THEN
    RETURN NULL;
  END IF;
  UPDATE hosted.recovery_challenges SET consumed_at = clock_timestamp()
    WHERE challenge_hash = p_hash
      AND purchase_session_id = p_session_id AND purchase_mode = p_mode
      AND mail_state = 'sent' AND consumed_at IS NULL
      AND expires_at > clock_timestamp();
  IF NOT FOUND THEN RETURN NULL; END IF;
  INSERT INTO hosted.device_sessions
    (token_hash, account_id, vault_id, device_id, expires_at)
    VALUES (p_device_token_hash, v_account, p_vault_id,
      p_device_id, clock_timestamp() + interval '29 days');
  RETURN v_account;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.claim_recovery_vault_device(
  text, text, text, uuid, uuid, text
) FROM PUBLIC;
