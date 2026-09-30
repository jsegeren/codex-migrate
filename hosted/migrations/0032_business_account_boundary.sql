-- Company ownership is a different authority from an individual's Mac-app
-- purchase. This migration records the boundary only: it does not enroll an
-- administrator or device, grant storage, or activate a business service.
ALTER TABLE hosted.accounts
  ADD COLUMN owner_kind text NOT NULL DEFAULT 'individual'
    CHECK (owner_kind IN ('individual', 'business'));
--> statement-breakpoint
ALTER TABLE hosted.accounts
  ADD CONSTRAINT hosted_accounts_owner_kind_unique
  UNIQUE (account_id, owner_kind);
--> statement-breakpoint
CREATE FUNCTION hosted.reject_account_owner_kind_change()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.owner_kind IS DISTINCT FROM OLD.owner_kind THEN
    RAISE EXCEPTION 'hosted_account_owner_kind_is_immutable';
  END IF;
  RETURN NEW;
END;
$$;
--> statement-breakpoint
CREATE TRIGGER hosted_account_owner_kind_immutable
  BEFORE UPDATE OF owner_kind ON hosted.accounts
  FOR EACH ROW EXECUTE FUNCTION hosted.reject_account_owner_kind_change();
--> statement-breakpoint
ALTER TABLE hosted.purchase_enrollments
  ADD COLUMN owner_kind text NOT NULL DEFAULT 'individual'
    CHECK (owner_kind = 'individual');
--> statement-breakpoint
ALTER TABLE hosted.purchase_enrollments
  ADD CONSTRAINT hosted_purchase_individual_account_fk
  FOREIGN KEY (account_id, owner_kind)
    REFERENCES hosted.accounts (account_id, owner_kind);
--> statement-breakpoint
CREATE TABLE hosted.business_accounts (
  account_id uuid PRIMARY KEY,
  owner_kind text NOT NULL DEFAULT 'business' CHECK (owner_kind = 'business'),
  organization_name text NOT NULL
    CHECK (length(btrim(organization_name)) BETWEEN 1 AND 160),
  approval_reference uuid NOT NULL UNIQUE,
  purchaser_contact_email text NOT NULL
    CHECK (length(purchaser_contact_email) BETWEEN 3 AND 254),
  admin_contact_email text NOT NULL
    CHECK (length(admin_contact_email) BETWEEN 3 AND 254),
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (account_id, owner_kind)
    REFERENCES hosted.accounts (account_id, owner_kind)
);
