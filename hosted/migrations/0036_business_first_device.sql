-- An approved worker must prove control of that seat's exact email before a
-- first Mac is paired. Pairing is metadata only; no entitlement, key custody,
-- upload, or recovery capability follows from this migration.
CREATE TABLE hosted.business_worker_challenges (
  account_id uuid NOT NULL,
  seat_id uuid NOT NULL,
  admin_session_hash text NOT NULL REFERENCES hosted.business_admin_sessions (token_hash),
  challenge_hash text NOT NULL UNIQUE CHECK (challenge_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  mail_state text NOT NULL DEFAULT 'pending'
    CHECK (mail_state IN ('pending', 'sent', 'rejected', 'uncertain')),
  consumed_at timestamptz,
  window_started_at timestamptz NOT NULL,
  requests_in_window integer NOT NULL CHECK (requests_in_window BETWEEN 1 AND 5),
  PRIMARY KEY (account_id, seat_id),
  FOREIGN KEY (account_id, seat_id)
    REFERENCES hosted.business_seats (account_id, seat_id),
  CHECK (expires_at > created_at AND expires_at <= created_at + interval '10 minutes'),
  CHECK (consumed_at IS NULL OR consumed_at >= created_at)
);
--> statement-breakpoint
CREATE FUNCTION hosted.issue_business_worker_challenge(
  p_admin_session_hash text, p_account_id uuid, p_seat_id uuid, p_hash text
) RETURNS text LANGUAGE plpgsql AS $$
DECLARE
  v_now timestamptz := clock_timestamp();
  v_contact text;
  v_issued uuid;
BEGIN
  IF p_admin_session_hash IS NULL OR p_account_id IS NULL OR
     p_seat_id IS NULL OR p_hash IS NULL OR
     p_hash !~ '^[0-9a-f]{64}$' THEN RETURN NULL; END IF;
  IF NOT EXISTS (
    SELECT 1 FROM hosted.business_admin_sessions AS a
    JOIN hosted.business_accounts AS b ON b.account_id = a.account_id
    WHERE a.token_hash = p_admin_session_hash
      AND a.account_id = p_account_id AND a.revoked_at IS NULL
      AND a.expires_at > v_now FOR SHARE OF b
  ) THEN RETURN NULL; END IF;
  SELECT worker_contact_email INTO v_contact FROM hosted.business_seats
    WHERE account_id = p_account_id AND seat_id = p_seat_id
      AND revoked_at IS NULL FOR SHARE;
  IF v_contact IS NULL OR EXISTS (
    SELECT 1 FROM hosted.business_seat_vaults
      WHERE account_id = p_account_id AND seat_id = p_seat_id
  ) THEN RETURN NULL; END IF;

  INSERT INTO hosted.business_worker_challenges
    (account_id, seat_id, admin_session_hash, challenge_hash, created_at, expires_at,
     window_started_at, requests_in_window)
    VALUES (p_account_id, p_seat_id, p_admin_session_hash, p_hash, v_now,
      v_now + interval '10 minutes', v_now, 1)
    ON CONFLICT (account_id, seat_id) DO UPDATE
      SET challenge_hash = excluded.challenge_hash,
          admin_session_hash = excluded.admin_session_hash,
          created_at = excluded.created_at,
          expires_at = excluded.expires_at,
          mail_state = 'pending', consumed_at = NULL,
          window_started_at = CASE
            WHEN hosted.business_worker_challenges.window_started_at <=
              v_now - interval '1 day' THEN v_now
            ELSE hosted.business_worker_challenges.window_started_at END,
          requests_in_window = CASE
            WHEN hosted.business_worker_challenges.window_started_at <=
              v_now - interval '1 day' THEN 1
            ELSE hosted.business_worker_challenges.requests_in_window + 1 END
      WHERE hosted.business_worker_challenges.created_at <=
          v_now - interval '10 minutes'
        AND (hosted.business_worker_challenges.window_started_at <=
          v_now - interval '1 day' OR
          hosted.business_worker_challenges.requests_in_window < 5)
    RETURNING seat_id INTO v_issued;
  IF v_issued IS NULL THEN RETURN NULL; END IF;
  RETURN v_contact;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.issue_business_worker_challenge(text, uuid, uuid, text)
  FROM PUBLIC;
--> statement-breakpoint
CREATE FUNCTION hosted.record_business_worker_challenge_delivery(
  p_hash text, p_state text
) RETURNS boolean LANGUAGE plpgsql AS $$
BEGIN
  IF p_hash IS NULL OR p_state IS NULL OR
     p_state NOT IN ('sent', 'rejected', 'uncertain') THEN RETURN false; END IF;
  UPDATE hosted.business_worker_challenges SET mail_state = p_state
    WHERE challenge_hash = p_hash AND mail_state = 'pending'
      AND expires_at > clock_timestamp();
  RETURN FOUND;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.record_business_worker_challenge_delivery(text, text)
  FROM PUBLIC;
--> statement-breakpoint
CREATE FUNCTION hosted.claim_business_first_device(
  p_account_id uuid, p_seat_id uuid, p_challenge_hash text,
  p_vault_id uuid, p_device_id uuid, p_device_token_hash text
) RETURNS uuid LANGUAGE plpgsql AS $$
DECLARE
  v_now timestamptz := clock_timestamp();
  v_seat uuid;
BEGIN
  IF p_account_id IS NULL OR p_seat_id IS NULL OR p_challenge_hash IS NULL OR
     p_vault_id IS NULL OR p_device_id IS NULL OR
     p_device_token_hash IS NULL OR
     p_device_token_hash !~ '^[0-9a-f]{64}$' THEN RETURN NULL; END IF;
  SELECT seat_id INTO v_seat FROM hosted.business_seats
    WHERE account_id = p_account_id AND seat_id = p_seat_id
      AND revoked_at IS NULL FOR UPDATE;
  IF v_seat IS NULL OR EXISTS (
    SELECT 1 FROM hosted.business_seat_vaults
      WHERE account_id = p_account_id AND seat_id = p_seat_id
  ) THEN RETURN NULL; END IF;
  UPDATE hosted.business_worker_challenges SET consumed_at = v_now
    WHERE account_id = p_account_id AND seat_id = p_seat_id
      AND challenge_hash = p_challenge_hash AND mail_state = 'sent'
      AND consumed_at IS NULL AND expires_at > v_now
      AND EXISTS (SELECT 1 FROM hosted.business_admin_sessions AS a
        WHERE a.token_hash = admin_session_hash AND a.account_id = p_account_id
          AND a.revoked_at IS NULL AND a.expires_at > v_now);
  IF NOT FOUND THEN RETURN NULL; END IF;

  INSERT INTO hosted.vaults (account_id, vault_id)
    VALUES (p_account_id, p_vault_id);
  INSERT INTO hosted.business_seat_vaults (account_id, seat_id, vault_id)
    VALUES (p_account_id, p_seat_id, p_vault_id);
  INSERT INTO hosted.business_device_sessions
    (token_hash, account_id, seat_id, vault_id, device_id, created_at, expires_at)
    VALUES (p_device_token_hash, p_account_id, p_seat_id,
      p_vault_id, p_device_id, v_now, v_now + interval '29 days');
  RETURN p_vault_id;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.claim_business_first_device(
  uuid, uuid, text, uuid, uuid, text
) FROM PUBLIC;
