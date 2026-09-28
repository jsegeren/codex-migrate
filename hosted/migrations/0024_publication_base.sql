-- Concurrent uploads are allowed, including failed/expired work awaiting
-- cleanup. Capture last-good when each reservation is created; only a
-- publication based on the still-current pointer may advance that Vault.
-- The account-row lock in reserve_upload serializes this capture with the
-- account-row lock used by every publication path.
ALTER TABLE hosted.upload_reservations
  ADD COLUMN base_snapshot_id uuid;
--> statement-breakpoint
ALTER TABLE hosted.upload_reservations
  ADD CONSTRAINT upload_base_snapshot_fk
  FOREIGN KEY (account_id, vault_id, base_snapshot_id)
  REFERENCES hosted.snapshots (account_id, vault_id, snapshot_id);
--> statement-breakpoint
CREATE FUNCTION hosted.capture_upload_base() RETURNS trigger
  LANGUAGE plpgsql AS $$
DECLARE
  v_base uuid;
BEGIN
  SELECT last_good_snapshot_id INTO v_base FROM hosted.vaults
    WHERE account_id = NEW.account_id AND vault_id = NEW.vault_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'hosted_reservation_invalid'; END IF;
  NEW.base_snapshot_id := v_base;
  RETURN NEW;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.capture_upload_base() FROM PUBLIC;
--> statement-breakpoint
CREATE TRIGGER capture_upload_base_before_insert
  BEFORE INSERT ON hosted.upload_reservations
  FOR EACH ROW EXECUTE FUNCTION hosted.capture_upload_base();
--> statement-breakpoint
CREATE FUNCTION hosted.require_publication_base() RETURNS trigger
  LANGUAGE plpgsql AS $$
DECLARE
  v_base uuid;
BEGIN
  IF NEW.last_good_snapshot_id IS NOT DISTINCT FROM OLD.last_good_snapshot_id THEN
    RETURN NEW;
  END IF;
  IF NEW.last_good_snapshot_id IS NULL THEN
    RAISE EXCEPTION 'hosted_publication_base_changed';
  END IF;
  SELECT reservation.base_snapshot_id INTO v_base
    FROM hosted.snapshots AS snapshot
    JOIN hosted.upload_reservations AS reservation
      ON reservation.reservation_id = snapshot.reservation_id
    WHERE snapshot.account_id = NEW.account_id
      AND snapshot.vault_id = NEW.vault_id
      AND snapshot.snapshot_id = NEW.last_good_snapshot_id;
  IF NOT FOUND OR v_base IS DISTINCT FROM OLD.last_good_snapshot_id THEN
    RAISE EXCEPTION 'hosted_publication_base_changed';
  END IF;
  RETURN NEW;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.require_publication_base() FROM PUBLIC;
--> statement-breakpoint
CREATE TRIGGER require_publication_base_before_update
  BEFORE UPDATE OF last_good_snapshot_id ON hosted.vaults
  FOR EACH ROW EXECUTE FUNCTION hosted.require_publication_base();
