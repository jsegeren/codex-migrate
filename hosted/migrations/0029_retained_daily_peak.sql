-- Internal usage estimate, not a bill or proof that R2 holds these bytes.
-- NULL means the ledger has no evidence for that day; never treat it as zero.
-- A day's peak includes the last value before UTC midnight and every change
-- through that day. Provider inventory must be reconciled before invoicing.
CREATE FUNCTION hosted.retained_daily_peak(p_account_id uuid, p_day date)
  RETURNS bigint LANGUAGE sql STABLE AS $$
  WITH bounds AS (
    SELECT p_day::timestamp AT TIME ZONE 'UTC' AS day_start,
           (p_day + 1)::timestamp AT TIME ZONE 'UTC' AS day_end
  ),
  opening AS (
    SELECT event.retained_bytes
      FROM hosted.retained_usage_events event, bounds
     WHERE event.account_id = p_account_id
       AND event.recorded_at < bounds.day_start
     ORDER BY event.recorded_at DESC, event.event_id DESC
     LIMIT 1
  ),
  changes AS (
    SELECT max(event.retained_bytes) AS peak_bytes
      FROM hosted.retained_usage_events event, bounds
     WHERE event.account_id = p_account_id
       AND event.recorded_at >= bounds.day_start
       AND event.recorded_at < bounds.day_end
  )
  SELECT CASE
    WHEN (SELECT retained_bytes FROM opening) IS NULL THEN
      (SELECT peak_bytes FROM changes)
    WHEN (SELECT peak_bytes FROM changes) IS NULL THEN
      (SELECT retained_bytes FROM opening)
    ELSE greatest((SELECT retained_bytes FROM opening),
                  (SELECT peak_bytes FROM changes))
  END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.retained_daily_peak(uuid, date) FROM PUBLIC;
