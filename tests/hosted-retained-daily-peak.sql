-- Synthetic UTC accounting fixtures. Never derive an invoice from this alone.
DO $$
DECLARE
  v_account uuid := '8d4c1ea9-c120-42c5-a767-475a0f13547a';
  v_other uuid := '8d4c1ea9-c120-42c5-a767-475a0f13547b';
BEGIN
  INSERT INTO hosted.accounts (account_id, allowance_bytes)
    VALUES (v_account, 1000), (v_other, 1000);
  -- The insert trigger supplies each account's zero baseline. Move those
  -- fixture events into the prior UTC day to model a complete billing day.
  UPDATE hosted.retained_usage_events
     SET recorded_at = '2026-09-28 23:00:00+00'
   WHERE account_id IN (v_account, v_other);
  INSERT INTO hosted.retained_usage_events
    (account_id, recorded_at, retained_bytes) VALUES
    (v_account, '2026-09-29 00:00:00+00', 100),
    (v_account, '2026-09-29 12:00:00+00', 250),
    (v_account, '2026-09-29 23:59:59+00', 90),
    (v_account, '2026-09-30 00:00:00+00', 40),
    (v_other, '2026-09-29 10:00:00+00', 900);
  IF hosted.retained_daily_peak(v_account, '2026-09-29') IS DISTINCT FROM 250 OR
     hosted.retained_daily_peak(v_account, '2026-09-30') IS DISTINCT FROM 90 OR
     hosted.retained_daily_peak(v_account, '2026-10-01') IS DISTINCT FROM 40 OR
     hosted.retained_daily_peak(v_account, '2026-09-27') IS NOT NULL OR
     hosted.retained_daily_peak(v_other, '2026-09-29') IS DISTINCT FROM 900 THEN
    RAISE EXCEPTION 'retained daily peaks are inaccurate or crossed accounts';
  END IF;
END;
$$;
