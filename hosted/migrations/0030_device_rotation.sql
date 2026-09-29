-- Dark server primitive for replacing an expiring Keychain-held device bearer.
-- The caller must first authenticate the old bearer and persist the newly
-- generated bearer in Keychain. This transaction never extends the old token;
-- a lost response is reconciled by resolving the new bearer, not by blindly
-- repeating a rotation. No HTTP route or scheduled client invokes it yet.
CREATE FUNCTION hosted.rotate_device_session(
  p_old_hash text, p_old_device_id uuid,
  p_new_hash text, p_new_device_id uuid
) RETURNS TABLE(account_id uuid, vault_id uuid)
LANGUAGE plpgsql AS $$
DECLARE
  v_account uuid;
  v_old hosted.device_sessions%ROWTYPE;
  v_now timestamptz;
BEGIN
  IF p_old_hash IS NULL OR p_old_hash !~ '^[0-9a-f]{64}$' OR
     p_new_hash IS NULL OR p_new_hash !~ '^[0-9a-f]{64}$' OR
     p_old_hash = p_new_hash OR p_old_device_id IS NULL OR
     p_new_device_id IS NULL OR p_old_device_id = p_new_device_id THEN
    RETURN;
  END IF;

  SELECT session.account_id INTO v_account
    FROM hosted.device_sessions AS session
    WHERE session.token_hash = p_old_hash
      AND session.device_id = p_old_device_id;
  IF NOT FOUND THEN RETURN; END IF;

  -- Match the account-first lock order used by pairing and capacity updates.
  -- Recheck the session after any wait; only an active, unexpired bearer may
  -- authorize one replacement for the same account and Vault.
  PERFORM 1 FROM hosted.accounts AS account
    WHERE account.account_id = v_account FOR UPDATE;
  IF NOT FOUND THEN RETURN; END IF;
  SELECT * INTO v_old FROM hosted.device_sessions AS session
    WHERE session.token_hash = p_old_hash
      AND session.device_id = p_old_device_id FOR UPDATE;
  IF NOT FOUND THEN RETURN; END IF;
  v_now := clock_timestamp();
  IF v_old.account_id <> v_account OR
     v_old.revoked_at IS NOT NULL OR v_old.expires_at <= v_now OR
     (SELECT count(*) FROM hosted.device_sessions AS session
       WHERE session.account_id = v_account
         AND session.vault_id = v_old.vault_id
         AND session.revoked_at IS NULL
         AND session.expires_at > v_now) > 16 THEN
    RETURN;
  END IF;

  UPDATE hosted.device_sessions SET revoked_at = v_now
    WHERE token_hash = p_old_hash;
  INSERT INTO hosted.device_sessions
    (token_hash, account_id, vault_id, device_id, created_at, expires_at)
    VALUES (p_new_hash, v_account, v_old.vault_id, p_new_device_id,
      v_now, v_now + interval '29 days');
  account_id := v_account;
  vault_id := v_old.vault_id;
  RETURN NEXT;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.rotate_device_session(text, uuid, text, uuid)
  FROM PUBLIC;
