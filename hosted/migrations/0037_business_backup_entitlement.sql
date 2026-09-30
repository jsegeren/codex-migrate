-- Dark, operator-approved sandbox allowance. Pairing a business device is
-- not an entitlement. No public path creates or updates this record, and
-- production upload routes remain closed until billing and recovery gates pass.
CREATE TABLE hosted.business_backup_entitlements (
  entitlement_id uuid PRIMARY KEY,
  account_id uuid NOT NULL REFERENCES hosted.business_accounts (account_id),
  approval_reference uuid NOT NULL UNIQUE,
  allowance_bytes bigint NOT NULL
    CHECK (allowance_bytes BETWEEN 1 AND 1000000000000),
  starts_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK (expires_at > starts_at AND expires_at <= starts_at + interval '90 days'),
  CHECK (revoked_at IS NULL OR revoked_at >= created_at)
);
--> statement-breakpoint
CREATE UNIQUE INDEX hosted_business_current_backup_entitlement
  ON hosted.business_backup_entitlements (account_id)
  WHERE revoked_at IS NULL;
--> statement-breakpoint
CREATE FUNCTION hosted.protect_business_backup_entitlement()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'hosted_business_entitlement_history_is_immutable';
  END IF;
  IF NEW.entitlement_id IS DISTINCT FROM OLD.entitlement_id OR
     NEW.account_id IS DISTINCT FROM OLD.account_id OR
     NEW.approval_reference IS DISTINCT FROM OLD.approval_reference OR
     NEW.allowance_bytes IS DISTINCT FROM OLD.allowance_bytes OR
     NEW.starts_at IS DISTINCT FROM OLD.starts_at OR
     NEW.expires_at IS DISTINCT FROM OLD.expires_at OR
     NEW.created_at IS DISTINCT FROM OLD.created_at OR
     (OLD.revoked_at IS NOT NULL AND
      NEW.revoked_at IS DISTINCT FROM OLD.revoked_at) THEN
    RAISE EXCEPTION 'hosted_business_entitlement_history_is_immutable';
  END IF;
  RETURN NEW;
END;
$$;
--> statement-breakpoint
CREATE TRIGGER hosted_business_entitlement_immutable
  BEFORE UPDATE OR DELETE ON hosted.business_backup_entitlements
  FOR EACH ROW EXECUTE FUNCTION hosted.protect_business_backup_entitlement();
