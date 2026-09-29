-- Account-scoped storage history for cost analysis, not an invoice.
-- This records the trusted SQL ledger whenever retained encrypted bytes
-- change. R2 may additionally hold uncommitted/orphan objects, so reconcile
-- provider inventory before charging from any derived GB-month figure.
CREATE TABLE hosted.retained_usage_events (
  event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  account_id uuid NOT NULL REFERENCES hosted.accounts (account_id),
  recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  retained_bytes bigint NOT NULL CHECK (retained_bytes >= 0)
);
--> statement-breakpoint
CREATE INDEX retained_usage_events_account_time
  ON hosted.retained_usage_events (account_id, recorded_at, event_id);
--> statement-breakpoint
-- Existing accounts begin at their current ledger value. This baseline says
-- nothing about earlier days and must never support retroactive billing.
INSERT INTO hosted.retained_usage_events (account_id, retained_bytes)
  SELECT account_id, retained_bytes FROM hosted.accounts;
--> statement-breakpoint
CREATE FUNCTION hosted.capture_retained_usage_event()
  RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    INSERT INTO hosted.retained_usage_events (account_id, retained_bytes)
      VALUES (NEW.account_id, NEW.retained_bytes);
  ELSIF OLD.retained_bytes IS DISTINCT FROM NEW.retained_bytes THEN
    INSERT INTO hosted.retained_usage_events (account_id, retained_bytes)
      VALUES (NEW.account_id, NEW.retained_bytes);
  END IF;
  RETURN NEW;
END;
$$;
--> statement-breakpoint
CREATE TRIGGER retained_usage_event
  AFTER INSERT OR UPDATE OF retained_bytes ON hosted.accounts
  FOR EACH ROW EXECUTE FUNCTION hosted.capture_retained_usage_event();
--> statement-breakpoint
REVOKE ALL ON hosted.retained_usage_events FROM PUBLIC;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.capture_retained_usage_event() FROM PUBLIC;
