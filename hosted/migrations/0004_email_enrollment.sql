-- Zero means a buyer has proved ownership but has not activated hosted
-- capacity. A device session and a paid/trial entitlement are still required
-- before an upload grant.
ALTER TABLE hosted.accounts DROP CONSTRAINT accounts_allowance_bytes_check;
--> statement-breakpoint
ALTER TABLE hosted.accounts ADD CONSTRAINT accounts_allowance_bytes_check
  CHECK (allowance_bytes >= 0);
--> statement-breakpoint
CREATE TABLE hosted.enrollment_challenges (
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
CREATE FUNCTION hosted.issue_enrollment_challenge(
  p_session_id text, p_mode text, p_hash text
) RETURNS boolean LANGUAGE plpgsql AS $$
DECLARE
  v_issued timestamptz := clock_timestamp();
  v_count integer;
BEGIN
  IF p_session_id IS NULL OR p_mode IS NULL OR
     p_mode NOT IN ('sandbox', 'live') OR
     p_hash IS NULL OR p_hash !~ '^[0-9a-f]{64}$' OR
     EXISTS (SELECT 1 FROM hosted.purchase_enrollments
       WHERE purchase_session_id = p_session_id AND purchase_mode = p_mode) THEN
    RETURN false;
  END IF;
  INSERT INTO hosted.enrollment_challenges
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
            WHEN hosted.enrollment_challenges.window_started_at <=
              v_issued - interval '1 day' THEN v_issued
            ELSE hosted.enrollment_challenges.window_started_at END,
          requests_in_window = CASE
            WHEN hosted.enrollment_challenges.window_started_at <=
              v_issued - interval '1 day' THEN 1
            ELSE hosted.enrollment_challenges.requests_in_window + 1 END
      WHERE hosted.enrollment_challenges.created_at <=
          v_issued - interval '10 minutes'
        AND (hosted.enrollment_challenges.window_started_at <=
          v_issued - interval '1 day' OR
          hosted.enrollment_challenges.requests_in_window < 5)
        AND NOT EXISTS (SELECT 1 FROM hosted.purchase_enrollments
          WHERE purchase_session_id = p_session_id AND purchase_mode = p_mode)
    RETURNING requests_in_window INTO v_count;
  RETURN FOUND;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.issue_enrollment_challenge(text, text, text)
  FROM PUBLIC;
--> statement-breakpoint
CREATE FUNCTION hosted.record_enrollment_challenge_delivery(
  p_hash text, p_state text
)
RETURNS boolean LANGUAGE plpgsql AS $$
BEGIN
  IF p_hash IS NULL OR p_state IS NULL OR
     p_state NOT IN ('sent', 'rejected', 'uncertain') THEN
    RETURN false;
  END IF;
  UPDATE hosted.enrollment_challenges SET mail_state = p_state
    WHERE challenge_hash = p_hash AND mail_state = 'pending'
      AND expires_at > clock_timestamp();
  RETURN FOUND;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.record_enrollment_challenge_delivery(text, text)
  FROM PUBLIC;
--> statement-breakpoint
CREATE FUNCTION hosted.claim_purchase_enrollment(
  p_hash text, p_session_id text, p_mode text, p_account_id uuid
) RETURNS uuid LANGUAGE plpgsql AS $$
BEGIN
  IF p_account_id IS NULL OR p_hash IS NULL OR p_session_id IS NULL OR
     p_mode IS NULL OR
     p_mode NOT IN ('sandbox', 'live') THEN RETURN NULL; END IF;
  UPDATE hosted.enrollment_challenges SET consumed_at = clock_timestamp()
    WHERE challenge_hash = p_hash AND purchase_session_id = p_session_id
      AND purchase_mode = p_mode AND mail_state = 'sent'
      AND consumed_at IS NULL AND expires_at > clock_timestamp();
  IF NOT FOUND THEN RETURN NULL; END IF;

  INSERT INTO hosted.accounts (account_id, allowance_bytes)
    VALUES (p_account_id, 0);
  INSERT INTO hosted.purchase_enrollments
    (account_id, purchase_session_id, purchase_mode)
    VALUES (p_account_id, p_session_id, p_mode);
  RETURN p_account_id;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.claim_purchase_enrollment(text, text, text, uuid)
  FROM PUBLIC;
