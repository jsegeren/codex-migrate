-- Inert business seat and device inventory. These rows do not authorize API
-- calls until an authenticated administrator approval and service entitlement
-- path are implemented. Personal device sessions remain purchase-bound.
CREATE TABLE hosted.business_seats (
  account_id uuid NOT NULL REFERENCES hosted.business_accounts (account_id),
  seat_id uuid NOT NULL,
  worker_contact_email text NOT NULL
    CHECK (length(worker_contact_email) BETWEEN 3 AND 254),
  approval_reference uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  revoked_at timestamptz,
  PRIMARY KEY (account_id, seat_id),
  UNIQUE (account_id, approval_reference),
  CHECK (revoked_at IS NULL OR revoked_at >= created_at)
);
--> statement-breakpoint
CREATE TABLE hosted.business_seat_vaults (
  account_id uuid NOT NULL,
  seat_id uuid NOT NULL,
  vault_id uuid NOT NULL,
  assigned_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (account_id, vault_id),
  UNIQUE (account_id, seat_id, vault_id),
  FOREIGN KEY (account_id, seat_id)
    REFERENCES hosted.business_seats (account_id, seat_id),
  FOREIGN KEY (account_id, vault_id)
    REFERENCES hosted.vaults (account_id, vault_id)
);
--> statement-breakpoint
CREATE TABLE hosted.business_device_sessions (
  token_hash text PRIMARY KEY CHECK (token_hash ~ '^[0-9a-f]{64}$'),
  account_id uuid NOT NULL,
  seat_id uuid NOT NULL,
  vault_id uuid NOT NULL,
  device_id uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  FOREIGN KEY (account_id, seat_id, vault_id)
    REFERENCES hosted.business_seat_vaults (account_id, seat_id, vault_id),
  CHECK (expires_at > created_at AND expires_at <= created_at + interval '30 days'),
  CHECK (revoked_at IS NULL OR revoked_at >= created_at)
);
--> statement-breakpoint
CREATE INDEX hosted_business_device_sessions_vault_idx
  ON hosted.business_device_sessions (account_id, seat_id, vault_id);
--> statement-breakpoint
CREATE FUNCTION hosted.require_active_business_seat()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM hosted.business_seats
      WHERE account_id = NEW.account_id AND seat_id = NEW.seat_id
        AND revoked_at IS NULL FOR SHARE
  ) THEN
    RAISE EXCEPTION 'hosted_business_seat_unavailable';
  END IF;
  RETURN NEW;
END;
$$;
--> statement-breakpoint
CREATE TRIGGER hosted_business_vault_active_seat
  BEFORE INSERT OR UPDATE OF account_id, seat_id, vault_id
  ON hosted.business_seat_vaults
  FOR EACH ROW EXECUTE FUNCTION hosted.require_active_business_seat();
--> statement-breakpoint
CREATE TRIGGER hosted_business_device_active_seat
  BEFORE INSERT OR UPDATE OF account_id, seat_id, vault_id
  ON hosted.business_device_sessions
  FOR EACH ROW EXECUTE FUNCTION hosted.require_active_business_seat();
--> statement-breakpoint
CREATE FUNCTION hosted.revoke_business_seat_sessions()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.revoked_at IS NOT NULL AND
     NEW.revoked_at IS DISTINCT FROM OLD.revoked_at THEN
    RAISE EXCEPTION 'hosted_business_seat_revocation_is_final';
  END IF;
  IF OLD.revoked_at IS NULL AND NEW.revoked_at IS NOT NULL THEN
    UPDATE hosted.business_device_sessions
      SET revoked_at = GREATEST(NEW.revoked_at, created_at)
      WHERE account_id = NEW.account_id AND seat_id = NEW.seat_id
        AND revoked_at IS NULL;
  END IF;
  RETURN NEW;
END;
$$;
--> statement-breakpoint
CREATE TRIGGER hosted_business_seat_revoke_devices
  BEFORE UPDATE OF revoked_at ON hosted.business_seats
  FOR EACH ROW EXECUTE FUNCTION hosted.revoke_business_seat_sessions();
