-- Assisted pilots have an operator-set seat ceiling. Email proof by the
-- approved administrator can allocate a seat, but it cannot grant storage,
-- enroll a device, or read any backed-up content.
ALTER TABLE hosted.business_accounts
  ADD COLUMN pilot_seat_limit integer NOT NULL DEFAULT 0
    CHECK (pilot_seat_limit BETWEEN 0 AND 1000);
--> statement-breakpoint
CREATE UNIQUE INDEX hosted_business_active_worker_seat_unique
  ON hosted.business_seats (account_id, worker_contact_email)
  WHERE revoked_at IS NULL;
--> statement-breakpoint
CREATE FUNCTION hosted.reject_business_seat_identity_change()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.account_id IS DISTINCT FROM OLD.account_id OR
     NEW.seat_id IS DISTINCT FROM OLD.seat_id OR
     NEW.worker_contact_email IS DISTINCT FROM OLD.worker_contact_email OR
     NEW.approval_reference IS DISTINCT FROM OLD.approval_reference THEN
    RAISE EXCEPTION 'hosted_business_seat_identity_is_immutable';
  END IF;
  RETURN NEW;
END;
$$;
--> statement-breakpoint
CREATE TRIGGER hosted_business_seat_identity_immutable
  BEFORE UPDATE OF account_id, seat_id, worker_contact_email, approval_reference
  ON hosted.business_seats
  FOR EACH ROW EXECUTE FUNCTION hosted.reject_business_seat_identity_change();
--> statement-breakpoint
CREATE TABLE hosted.business_admin_actions (
  action_id uuid PRIMARY KEY,
  account_id uuid NOT NULL REFERENCES hosted.business_accounts (account_id),
  actor_session_hash text NOT NULL REFERENCES hosted.business_admin_sessions (token_hash),
  admin_contact_at_action text NOT NULL,
  action_kind text NOT NULL CHECK (action_kind = 'approve_seat'),
  seat_id uuid NOT NULL,
  approval_reference uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (account_id, action_kind, seat_id),
  UNIQUE (account_id, action_kind, approval_reference)
);
--> statement-breakpoint
CREATE FUNCTION hosted.reject_business_admin_action_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'hosted_business_admin_action_is_immutable';
END;
$$;
--> statement-breakpoint
CREATE TRIGGER hosted_business_admin_actions_immutable
  BEFORE UPDATE OR DELETE ON hosted.business_admin_actions
  FOR EACH ROW EXECUTE FUNCTION hosted.reject_business_admin_action_mutation();
--> statement-breakpoint
CREATE FUNCTION hosted.approve_business_seat(
  p_session_hash text, p_seat_id uuid, p_worker_email text,
  p_approval_reference uuid, p_action_id uuid
) RETURNS uuid LANGUAGE plpgsql AS $$
DECLARE
  v_account uuid;
  v_admin_contact text;
  v_limit integer;
  v_existing hosted.business_seats%ROWTYPE;
  v_now timestamptz := clock_timestamp();
BEGIN
  IF p_session_hash IS NULL OR p_seat_id IS NULL OR
     p_worker_email IS NULL OR p_approval_reference IS NULL OR
     p_action_id IS NULL OR length(p_worker_email) NOT BETWEEN 3 AND 254 OR
     p_worker_email <> lower(p_worker_email) OR
     p_worker_email !~ '^[^[:space:]<>@]+@[^[:space:]<>@]+\.[^[:space:]<>@]+$' THEN
    RETURN NULL;
  END IF;

  -- Serialize all seat allocations and contact changes for this company.
  SELECT b.account_id, b.admin_contact_email, b.pilot_seat_limit
    INTO v_account, v_admin_contact, v_limit
    FROM hosted.business_admin_sessions AS s
    JOIN hosted.business_accounts AS b ON b.account_id = s.account_id
    WHERE s.token_hash = p_session_hash AND s.revoked_at IS NULL
      AND s.expires_at > v_now
    FOR UPDATE OF b;
  IF v_account IS NULL THEN RETURN NULL; END IF;

  SELECT * INTO v_existing FROM hosted.business_seats
    WHERE account_id = v_account AND seat_id = p_seat_id;
  IF FOUND THEN
    -- A lost response can be reconciled only for the exact original approval.
    IF v_existing.worker_contact_email = p_worker_email AND
       v_existing.approval_reference = p_approval_reference AND
       v_existing.revoked_at IS NULL THEN RETURN p_seat_id; END IF;
    RETURN NULL;
  END IF;
  IF v_limit = 0 OR (SELECT count(*) FROM hosted.business_seats
      WHERE account_id = v_account AND revoked_at IS NULL) >= v_limit THEN
    RETURN NULL;
  END IF;

  INSERT INTO hosted.business_seats
    (account_id, seat_id, worker_contact_email, approval_reference)
    VALUES (v_account, p_seat_id, p_worker_email, p_approval_reference);
  INSERT INTO hosted.business_admin_actions
    (action_id, account_id, actor_session_hash, admin_contact_at_action,
     action_kind, seat_id, approval_reference)
    VALUES (p_action_id, v_account, p_session_hash, v_admin_contact,
      'approve_seat', p_seat_id, p_approval_reference);
  RETURN p_seat_id;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.approve_business_seat(text, uuid, text, uuid, uuid)
  FROM PUBLIC;
