-- A replacement Mac may read one existing business Vault only after a fresh,
-- recorded administrator request and a second code delivered to the exact
-- operator-approved company contact. This never grants upload or decryption.
ALTER TABLE hosted.business_device_sessions
  ADD COLUMN access_purpose text NOT NULL DEFAULT 'worker'
    CHECK (access_purpose IN ('worker', 'recovery'));
--> statement-breakpoint
CREATE TABLE hosted.business_recovery_requests (
  request_id uuid PRIMARY KEY,
  account_id uuid NOT NULL,
  seat_id uuid NOT NULL,
  vault_id uuid NOT NULL,
  admin_session_hash text NOT NULL,
  purpose text NOT NULL CHECK (length(purpose) BETWEEN 12 AND 250),
  challenge_hash text NOT NULL UNIQUE CHECK (challenge_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  mail_state text NOT NULL DEFAULT 'pending'
    CHECK (mail_state IN ('pending', 'sent', 'rejected', 'uncertain')),
  consumed_at timestamptz,
  device_id uuid,
  device_token_hash text CHECK (device_token_hash ~ '^[0-9a-f]{64}$'),
  FOREIGN KEY (account_id, seat_id, vault_id)
    REFERENCES hosted.business_seat_vaults (account_id, seat_id, vault_id),
  CHECK (expires_at > created_at AND expires_at <= created_at + interval '10 minutes'),
  CHECK ((consumed_at IS NULL AND device_id IS NULL AND device_token_hash IS NULL)
      OR (consumed_at IS NOT NULL AND device_id IS NOT NULL
          AND device_token_hash IS NOT NULL))
);
--> statement-breakpoint
CREATE INDEX hosted_business_recovery_requests_limit_idx
  ON hosted.business_recovery_requests (account_id, seat_id, created_at DESC);
--> statement-breakpoint
CREATE TABLE hosted.business_recovery_audit (
  request_id uuid PRIMARY KEY REFERENCES hosted.business_recovery_requests (request_id),
  account_id uuid NOT NULL,
  seat_id uuid NOT NULL,
  vault_id uuid NOT NULL,
  admin_session_hash text NOT NULL,
  purpose text NOT NULL,
  device_id uuid NOT NULL,
  device_token_hash text NOT NULL,
  authorized_at timestamptz NOT NULL
);
--> statement-breakpoint
CREATE FUNCTION hosted.refuse_business_recovery_audit_change()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'hosted_business_recovery_audit_is_immutable';
END;
$$;
--> statement-breakpoint
CREATE TRIGGER hosted_business_recovery_audit_immutable
  BEFORE UPDATE OR DELETE ON hosted.business_recovery_audit
  FOR EACH ROW EXECUTE FUNCTION hosted.refuse_business_recovery_audit_change();
--> statement-breakpoint
CREATE FUNCTION hosted.issue_business_recovery_request(
  p_admin_session_hash text, p_account_id uuid, p_seat_id uuid,
  p_vault_id uuid, p_request_id uuid, p_purpose text, p_challenge_hash text
) RETURNS text LANGUAGE plpgsql AS $$
DECLARE
  v_now timestamptz := clock_timestamp();
  v_contact text;
BEGIN
  IF p_admin_session_hash IS NULL OR p_account_id IS NULL OR
     p_seat_id IS NULL OR p_vault_id IS NULL OR p_request_id IS NULL OR
     p_purpose IS NULL OR length(p_purpose) NOT BETWEEN 12 AND 250 OR
     p_purpose != btrim(p_purpose) OR p_purpose ~ '[[:cntrl:]]' OR
     p_challenge_hash IS NULL OR p_challenge_hash !~ '^[0-9a-f]{64}$' THEN
    RETURN NULL;
  END IF;
  SELECT b.admin_contact_email INTO v_contact
    FROM hosted.business_seats AS s
    JOIN hosted.business_seat_vaults AS v
      ON v.account_id = s.account_id AND v.seat_id = s.seat_id
    JOIN hosted.business_accounts AS b ON b.account_id = s.account_id
    WHERE s.account_id = p_account_id AND s.seat_id = p_seat_id
      AND v.vault_id = p_vault_id AND s.revoked_at IS NULL
      AND EXISTS (SELECT 1 FROM hosted.business_admin_sessions AS a
        WHERE a.token_hash = p_admin_session_hash AND a.account_id = p_account_id
          AND a.revoked_at IS NULL AND a.expires_at > v_now)
    FOR UPDATE OF s;
  IF v_contact IS NULL OR (SELECT count(*) FROM hosted.business_recovery_requests
      WHERE account_id = p_account_id AND seat_id = p_seat_id
        AND created_at > v_now - interval '1 day') >= 5 THEN
    RETURN NULL;
  END IF;
  INSERT INTO hosted.business_recovery_requests
    (request_id, account_id, seat_id, vault_id, admin_session_hash,
     purpose, challenge_hash, created_at, expires_at)
    VALUES (p_request_id, p_account_id, p_seat_id, p_vault_id,
      p_admin_session_hash, p_purpose, p_challenge_hash, v_now,
      v_now + interval '10 minutes');
  RETURN v_contact;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.issue_business_recovery_request(
  text, uuid, uuid, uuid, uuid, text, text) FROM PUBLIC;
--> statement-breakpoint
CREATE FUNCTION hosted.record_business_recovery_delivery(p_hash text, p_state text)
RETURNS boolean LANGUAGE plpgsql AS $$
BEGIN
  IF p_hash IS NULL OR p_state NOT IN ('sent', 'rejected', 'uncertain') THEN
    RETURN false;
  END IF;
  UPDATE hosted.business_recovery_requests SET mail_state = p_state
    WHERE challenge_hash = p_hash AND mail_state = 'pending'
      AND expires_at > clock_timestamp();
  RETURN FOUND;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.record_business_recovery_delivery(text, text)
  FROM PUBLIC;
--> statement-breakpoint
CREATE FUNCTION hosted.claim_business_recovery_device(
  p_account_id uuid, p_seat_id uuid, p_vault_id uuid,
  p_request_id uuid, p_challenge_hash text, p_device_id uuid,
  p_device_token_hash text
) RETURNS uuid LANGUAGE plpgsql AS $$
DECLARE
  v_now timestamptz := clock_timestamp();
  v_request hosted.business_recovery_requests%ROWTYPE;
BEGIN
  IF p_account_id IS NULL OR p_seat_id IS NULL OR p_vault_id IS NULL OR
     p_request_id IS NULL OR p_challenge_hash IS NULL OR p_device_id IS NULL OR
     p_device_token_hash IS NULL OR
     p_device_token_hash !~ '^[0-9a-f]{64}$' THEN RETURN NULL; END IF;
  UPDATE hosted.business_recovery_requests AS r
    SET consumed_at = v_now, device_id = p_device_id,
        device_token_hash = p_device_token_hash
    WHERE r.request_id = p_request_id AND r.account_id = p_account_id
      AND r.seat_id = p_seat_id AND r.vault_id = p_vault_id
      AND r.challenge_hash = p_challenge_hash
      AND r.mail_state = 'sent' AND r.consumed_at IS NULL AND r.expires_at > v_now
      AND EXISTS (SELECT 1 FROM hosted.business_admin_sessions AS a
        WHERE a.token_hash = r.admin_session_hash AND a.account_id = r.account_id
          AND a.revoked_at IS NULL AND a.expires_at > v_now)
      AND EXISTS (SELECT 1 FROM hosted.business_seats AS s
        WHERE s.account_id = r.account_id AND s.seat_id = r.seat_id
          AND s.revoked_at IS NULL)
    RETURNING r.* INTO v_request;
  IF v_request.request_id IS NULL THEN RETURN NULL; END IF;
  INSERT INTO hosted.business_device_sessions
    (token_hash, account_id, seat_id, vault_id, device_id,
     created_at, expires_at, access_purpose)
    VALUES (p_device_token_hash, v_request.account_id, v_request.seat_id,
      v_request.vault_id, p_device_id, v_now, v_now + interval '2 hours',
      'recovery');
  INSERT INTO hosted.business_recovery_audit
    (request_id, account_id, seat_id, vault_id, admin_session_hash,
     purpose, device_id, device_token_hash, authorized_at)
    VALUES (v_request.request_id, v_request.account_id, v_request.seat_id,
      v_request.vault_id, v_request.admin_session_hash, v_request.purpose,
      p_device_id, p_device_token_hash, v_now);
  RETURN v_request.vault_id;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.claim_business_recovery_device(
  uuid, uuid, uuid, uuid, text, uuid, text) FROM PUBLIC;
