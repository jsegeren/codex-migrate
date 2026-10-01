-- Dark business-health alert ledger. A scan is independent of the Mac: an
-- offline worker cannot suppress a missed-backup signal. Delivery is at most
-- once per incident; an ambiguous mail result requires human reconciliation.
CREATE VIEW hosted.business_backup_health_status AS
SELECT s.account_id, s.seat_id, sv.vault_id,
  CASE
    WHEN s.revoked_at IS NOT NULL THEN NULL
    WHEN sv.vault_id IS NULL THEN 'not_enrolled'
    WHEN v.last_good_snapshot_id IS NULL THEN 'no_published_backup'
    WHEN c.checked_at IS NULL THEN 'no_check'
    WHEN c.reported_state = 'failed' THEN 'failed_run'
    WHEN c.checked_at < clock_timestamp() - interval '90 minutes' THEN 'overdue'
    WHEN c.reported_state = 'needs_attention' THEN 'worker_attention'
    WHEN c.reported_snapshot_id IS DISTINCT FROM
      v.last_good_snapshot_id THEN 'snapshot_mismatch'
    WHEN latest.source_coverage IS DISTINCT FROM 'complete' THEN
      'incomplete_sources'
    ELSE NULL
  END AS reason
FROM hosted.business_seats AS s
JOIN hosted.business_backup_entitlements AS entitlement
  ON entitlement.account_id = s.account_id
    AND entitlement.revoked_at IS NULL
    AND entitlement.starts_at <= clock_timestamp()
    AND entitlement.expires_at > clock_timestamp()
LEFT JOIN hosted.business_seat_vaults AS sv
  ON sv.account_id = s.account_id AND sv.seat_id = s.seat_id
LEFT JOIN hosted.vaults AS v
  ON v.account_id = sv.account_id AND v.vault_id = sv.vault_id
LEFT JOIN hosted.snapshots AS latest
  ON latest.account_id = v.account_id AND latest.vault_id = v.vault_id
    AND latest.snapshot_id = v.last_good_snapshot_id
LEFT JOIN hosted.business_backup_checks AS c
  ON c.account_id = sv.account_id AND c.vault_id = sv.vault_id;
--> statement-breakpoint
CREATE TABLE hosted.business_backup_alerts (
  alert_id uuid PRIMARY KEY,
  account_id uuid NOT NULL,
  seat_id uuid NOT NULL,
  vault_id uuid,
  reason text NOT NULL CHECK (reason IN ('not_enrolled',
    'no_published_backup', 'no_check', 'failed_run', 'overdue',
    'worker_attention', 'snapshot_mismatch', 'incomplete_sources')),
  detected_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  claimed_at timestamptz,
  delivery_state text NOT NULL DEFAULT 'pending'
    CHECK (delivery_state IN ('pending', 'claimed', 'accepted',
      'rejected', 'uncertain')),
  delivery_recorded_at timestamptz,
  resolved_at timestamptz,
  FOREIGN KEY (account_id, seat_id)
    REFERENCES hosted.business_seats (account_id, seat_id),
  CHECK ((claimed_at IS NULL) = (delivery_state = 'pending')),
  CHECK ((delivery_recorded_at IS NULL) =
    (delivery_state IN ('pending', 'claimed')))
);
--> statement-breakpoint
CREATE UNIQUE INDEX business_backup_one_open_alert_per_vault
  ON hosted.business_backup_alerts (account_id, seat_id,
    coalesce(vault_id, '00000000-0000-0000-0000-000000000000'::uuid))
  WHERE resolved_at IS NULL;
--> statement-breakpoint
CREATE FUNCTION hosted.claim_business_backup_alerts()
RETURNS TABLE(alert_id uuid, admin_contact_email text,
  seat_id uuid, reason text)
LANGUAGE plpgsql AS $$
BEGIN
  -- Serialize scans while leaving worker check-ins free to proceed.
  PERFORM pg_advisory_xact_lock(7041, 1);
  UPDATE hosted.business_backup_alerts AS a
    SET resolved_at = clock_timestamp()
    WHERE a.resolved_at IS NULL AND NOT EXISTS (
      SELECT 1 FROM hosted.business_backup_health_status AS h
        WHERE h.account_id = a.account_id AND h.seat_id = a.seat_id
          AND h.vault_id IS NOT DISTINCT FROM a.vault_id
          AND h.reason IS NOT NULL);
  UPDATE hosted.business_backup_alerts AS a SET reason = h.reason
    FROM hosted.business_backup_health_status AS h
    WHERE a.resolved_at IS NULL AND a.account_id = h.account_id
      AND a.seat_id = h.seat_id
      AND a.vault_id IS NOT DISTINCT FROM h.vault_id
      AND h.reason IS NOT NULL AND a.reason IS DISTINCT FROM h.reason;
  INSERT INTO hosted.business_backup_alerts AS a
    (alert_id, account_id, seat_id, vault_id, reason)
    SELECT gen_random_uuid(), h.account_id, h.seat_id, h.vault_id, h.reason
      FROM hosted.business_backup_health_status AS h
      WHERE h.reason IS NOT NULL
    ON CONFLICT DO NOTHING;
  RETURN QUERY WITH picked AS (
    SELECT a.alert_id FROM hosted.business_backup_alerts AS a
      WHERE a.delivery_state = 'pending' AND a.resolved_at IS NULL
      ORDER BY a.detected_at, a.alert_id LIMIT 3 FOR UPDATE SKIP LOCKED
  ), claimed AS (
    UPDATE hosted.business_backup_alerts AS a
      SET delivery_state = 'claimed', claimed_at = clock_timestamp()
      FROM picked WHERE a.alert_id = picked.alert_id
      RETURNING a.alert_id, a.account_id, a.seat_id, a.reason
  ) SELECT claimed.alert_id, b.admin_contact_email,
      claimed.seat_id, claimed.reason FROM claimed
    JOIN hosted.business_accounts AS b
      ON b.account_id = claimed.account_id;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.claim_business_backup_alerts() FROM PUBLIC;
--> statement-breakpoint
CREATE FUNCTION hosted.record_business_backup_alert_delivery(
  p_alert_id uuid, p_state text) RETURNS boolean
LANGUAGE plpgsql AS $$
BEGIN
  IF p_alert_id IS NULL OR p_state IS NULL OR p_state NOT IN
      ('accepted', 'rejected', 'uncertain') THEN RETURN false; END IF;
  UPDATE hosted.business_backup_alerts SET delivery_state = p_state,
    delivery_recorded_at = clock_timestamp()
    WHERE alert_id = p_alert_id AND delivery_state = 'claimed';
  RETURN FOUND;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.record_business_backup_alert_delivery(
  uuid, text) FROM PUBLIC;
