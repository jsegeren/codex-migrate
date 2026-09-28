-- A lost reserve response is safe to retry with a client-recorded ID. The
-- account lock and exact ownership/state checks prevent another reservation.
BEGIN;
INSERT INTO hosted.accounts (account_id, allowance_bytes)
  VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 100);
INSERT INTO hosted.vaults (account_id, vault_id) VALUES
  ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
   'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'),
  ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
   'cccccccc-cccc-4ccc-8ccc-cccccccccccc');

DO $$
DECLARE
  v_account uuid := 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  v_vault uuid := 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
  v_other_vault uuid := 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
  v_reservation uuid := '11111111-1111-4111-8111-111111111111';
  v_allowed boolean;
  v_base uuid;
  v_expiry timestamptz;
  v_original_expiry timestamptz;
BEGIN
  SELECT allowed, base_snapshot_id, expires_at
    INTO v_allowed, v_base, v_expiry
    FROM hosted.reserve_upload_idempotent_current(v_account, v_vault,
      v_reservation, 1, clock_timestamp() + interval '40 minutes', 100);
  IF v_allowed IS NOT TRUE OR v_base IS NOT NULL OR v_expiry IS NULL THEN
    RAISE EXCEPTION 'first reservation failed';
  END IF;
  v_original_expiry := v_expiry;
  SELECT allowed, base_snapshot_id, expires_at
    INTO v_allowed, v_base, v_expiry
    FROM hosted.reserve_upload_idempotent_current(v_account, v_vault,
      v_reservation, 1, clock_timestamp() + interval '50 minutes', 100);
  IF v_allowed IS NOT TRUE OR v_base IS NOT NULL OR
     v_expiry IS DISTINCT FROM v_original_expiry OR
     (SELECT reserved_bytes FROM hosted.accounts
      WHERE account_id = v_account) <> 1 OR
     (SELECT count(*) FROM hosted.upload_reservations
      WHERE account_id = v_account) <> 1 THEN
    RAISE EXCEPTION 'retry changed quota, expiry, or reservation identity';
  END IF;

  SELECT allowed, base_snapshot_id, expires_at
    INTO v_allowed, v_base, v_expiry
    FROM hosted.reserve_upload_idempotent_current(v_account, v_other_vault,
      v_reservation, 1, clock_timestamp() + interval '50 minutes', 100);
  IF v_allowed IS NOT FALSE OR v_base IS NOT NULL OR v_expiry IS NOT NULL THEN
    RAISE EXCEPTION 'foreign Vault reused a reservation';
  END IF;

  UPDATE hosted.upload_reservations SET state = 'cleanup_pending'
    WHERE reservation_id = v_reservation;
  SELECT allowed, base_snapshot_id, expires_at
    INTO v_allowed, v_base, v_expiry
    FROM hosted.reserve_upload_idempotent_current(v_account, v_vault,
      v_reservation, 1, clock_timestamp() + interval '50 minutes', 100);
  IF v_allowed IS NOT FALSE OR v_base IS NOT NULL OR v_expiry IS NOT NULL THEN
    RAISE EXCEPTION 'quarantined reservation was revived';
  END IF;
END;
$$;
ROLLBACK;
