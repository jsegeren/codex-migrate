-- Disposable PostgreSQL only, after hosted migration 0028.
DO $$
DECLARE
  v_account uuid := '99999999-9999-4999-8999-999999999999';
BEGIN
  IF (SELECT count(*) FROM hosted.retained_usage_events
        WHERE account_id = v_account AND retained_bytes = 125) <> 1 THEN
    RAISE EXCEPTION 'pre-existing account baseline was not backfilled';
  END IF;
END;
$$;
DELETE FROM hosted.retained_usage_events
  WHERE account_id = '99999999-9999-4999-8999-999999999999';
DELETE FROM hosted.accounts
  WHERE account_id = '99999999-9999-4999-8999-999999999999';

BEGIN;
INSERT INTO hosted.accounts (account_id, allowance_bytes, retained_bytes)
  VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 1000, 10);
DO $$
DECLARE
  v_account uuid := 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  v_values bigint[];
BEGIN
  SELECT array_agg(retained_bytes ORDER BY event_id) INTO v_values
    FROM hosted.retained_usage_events WHERE account_id = v_account;
  IF v_values <> ARRAY[10]::bigint[] THEN
    RAISE EXCEPTION 'new account baseline missing';
  END IF;

  UPDATE hosted.accounts SET reserved_bytes = 5 WHERE account_id = v_account;
  UPDATE hosted.accounts SET retained_bytes = 10 WHERE account_id = v_account;
  SELECT array_agg(retained_bytes ORDER BY event_id) INTO v_values
    FROM hosted.retained_usage_events WHERE account_id = v_account;
  IF v_values <> ARRAY[10]::bigint[] THEN
    RAISE EXCEPTION 'unchanged storage created a usage event';
  END IF;

  UPDATE hosted.accounts SET retained_bytes = 30 WHERE account_id = v_account;
  UPDATE hosted.accounts SET retained_bytes = 15 WHERE account_id = v_account;
  SELECT array_agg(retained_bytes ORDER BY event_id) INTO v_values
    FROM hosted.retained_usage_events WHERE account_id = v_account;
  IF v_values <> ARRAY[10, 30, 15]::bigint[] THEN
    RAISE EXCEPTION 'storage changes were not recorded exactly once';
  END IF;
END;
$$;
ROLLBACK;
