-- Assisted-pilot administrator proof is tied to the exact contact manually
-- approved for an explicit business account. Email-domain similarity never
-- selects an account. An admin session is metadata-only until separate,
-- audited enrollment and recovery APIs are approved.
CREATE TABLE hosted.business_admin_challenges (
  account_id uuid PRIMARY KEY REFERENCES hosted.business_accounts (account_id),
  challenge_hash text NOT NULL UNIQUE CHECK (challenge_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  mail_state text NOT NULL DEFAULT 'pending'
    CHECK (mail_state IN ('pending', 'sent', 'rejected', 'uncertain')),
  consumed_at timestamptz,
  window_started_at timestamptz NOT NULL,
  requests_in_window integer NOT NULL CHECK (requests_in_window BETWEEN 1 AND 5),
  CHECK (expires_at > created_at AND expires_at <= created_at + interval '10 minutes'),
  CHECK (consumed_at IS NULL OR consumed_at >= created_at)
);
--> statement-breakpoint
CREATE TABLE hosted.business_admin_sessions (
  token_hash text PRIMARY KEY CHECK (token_hash ~ '^[0-9a-f]{64}$'),
  account_id uuid NOT NULL REFERENCES hosted.business_accounts (account_id),
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  CHECK (expires_at > created_at AND expires_at <= created_at + interval '12 hours'),
  CHECK (revoked_at IS NULL OR revoked_at >= created_at)
);
--> statement-breakpoint
CREATE INDEX hosted_business_admin_sessions_account_idx
  ON hosted.business_admin_sessions (account_id);
--> statement-breakpoint
CREATE FUNCTION hosted.issue_business_admin_challenge(
  p_account_id uuid, p_hash text
) RETURNS text LANGUAGE plpgsql AS $$
DECLARE
  v_issued timestamptz := clock_timestamp();
  v_contact text;
  v_account uuid;
BEGIN
  IF p_account_id IS NULL OR p_hash IS NULL OR
     p_hash !~ '^[0-9a-f]{64}$' THEN RETURN NULL; END IF;
  SELECT admin_contact_email INTO v_contact
    FROM hosted.business_accounts WHERE account_id = p_account_id FOR SHARE;
  IF v_contact IS NULL THEN RETURN NULL; END IF;

  INSERT INTO hosted.business_admin_challenges
    (account_id, challenge_hash, created_at, expires_at,
     window_started_at, requests_in_window)
    VALUES (p_account_id, p_hash, v_issued, v_issued + interval '10 minutes',
      v_issued, 1)
    ON CONFLICT (account_id) DO UPDATE
      SET challenge_hash = excluded.challenge_hash,
          created_at = excluded.created_at,
          expires_at = excluded.expires_at,
          mail_state = 'pending',
          consumed_at = NULL,
          window_started_at = CASE
            WHEN hosted.business_admin_challenges.window_started_at <=
              v_issued - interval '1 day' THEN v_issued
            ELSE hosted.business_admin_challenges.window_started_at END,
          requests_in_window = CASE
            WHEN hosted.business_admin_challenges.window_started_at <=
              v_issued - interval '1 day' THEN 1
            ELSE hosted.business_admin_challenges.requests_in_window + 1 END
      WHERE hosted.business_admin_challenges.created_at <=
          v_issued - interval '10 minutes'
        AND (hosted.business_admin_challenges.window_started_at <=
          v_issued - interval '1 day' OR
          hosted.business_admin_challenges.requests_in_window < 5)
    RETURNING account_id INTO v_account;
  IF v_account IS NULL THEN RETURN NULL; END IF;
  RETURN v_contact;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.issue_business_admin_challenge(uuid, text)
  FROM PUBLIC;
--> statement-breakpoint
CREATE FUNCTION hosted.record_business_admin_challenge_delivery(
  p_hash text, p_state text
) RETURNS boolean LANGUAGE plpgsql AS $$
BEGIN
  IF p_hash IS NULL OR p_state IS NULL OR
     p_state NOT IN ('sent', 'rejected', 'uncertain') THEN RETURN false; END IF;
  UPDATE hosted.business_admin_challenges SET mail_state = p_state
    WHERE challenge_hash = p_hash AND mail_state = 'pending'
      AND expires_at > clock_timestamp();
  RETURN FOUND;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.record_business_admin_challenge_delivery(text, text)
  FROM PUBLIC;
--> statement-breakpoint
CREATE FUNCTION hosted.claim_business_admin_session(
  p_account_id uuid, p_challenge_hash text, p_session_hash text
) RETURNS uuid LANGUAGE plpgsql AS $$
DECLARE
  v_account uuid;
  v_now timestamptz := clock_timestamp();
BEGIN
  IF p_account_id IS NULL OR p_challenge_hash IS NULL OR
     p_session_hash IS NULL OR p_session_hash !~ '^[0-9a-f]{64}$' THEN
    RETURN NULL;
  END IF;
  UPDATE hosted.business_admin_challenges SET consumed_at = v_now
    WHERE account_id = p_account_id AND challenge_hash = p_challenge_hash
      AND mail_state = 'sent' AND consumed_at IS NULL AND expires_at > v_now
    RETURNING account_id INTO v_account;
  IF v_account IS NULL THEN RETURN NULL; END IF;
  INSERT INTO hosted.business_admin_sessions
    (token_hash, account_id, created_at, expires_at) VALUES
    (p_session_hash, v_account, v_now, v_now + interval '12 hours');
  RETURN v_account;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.claim_business_admin_session(uuid, text, text)
  FROM PUBLIC;
--> statement-breakpoint
CREATE FUNCTION hosted.invalidate_business_admin_on_contact_change()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  v_now timestamptz := clock_timestamp();
BEGIN
  IF NEW.approval_reference IS DISTINCT FROM OLD.approval_reference THEN
    RAISE EXCEPTION 'hosted_business_approval_reference_is_immutable';
  END IF;
  IF NEW.admin_contact_email IS DISTINCT FROM OLD.admin_contact_email THEN
    UPDATE hosted.business_admin_challenges
      SET consumed_at = GREATEST(v_now, created_at), mail_state = 'rejected'
      WHERE account_id = OLD.account_id;
    UPDATE hosted.business_admin_sessions
      SET revoked_at = GREATEST(v_now, created_at)
      WHERE account_id = OLD.account_id AND revoked_at IS NULL;
  END IF;
  RETURN NEW;
END;
$$;
--> statement-breakpoint
CREATE TRIGGER hosted_business_admin_contact_change
  BEFORE UPDATE OF admin_contact_email, approval_reference
  ON hosted.business_accounts
  FOR EACH ROW EXECUTE FUNCTION hosted.invalidate_business_admin_on_contact_change();
--> statement-breakpoint
CREATE FUNCTION hosted.reject_business_admin_session_reactivation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.revoked_at IS NOT NULL AND
     NEW.revoked_at IS DISTINCT FROM OLD.revoked_at THEN
    RAISE EXCEPTION 'hosted_business_admin_revocation_is_final';
  END IF;
  RETURN NEW;
END;
$$;
--> statement-breakpoint
CREATE TRIGGER hosted_business_admin_session_revocation_final
  BEFORE UPDATE OF revoked_at ON hosted.business_admin_sessions
  FOR EACH ROW EXECUTE FUNCTION hosted.reject_business_admin_session_reactivation();
