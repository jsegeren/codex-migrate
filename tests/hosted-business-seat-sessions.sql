-- Disposable PostgreSQL after migration 0033. Assignment is exact by account,
-- seat, and Vault; none of these rows is an active API credential yet.
BEGIN;
INSERT INTO hosted.accounts (account_id, allowance_bytes, owner_kind) VALUES
  ('33333333-3333-4333-8333-333333333331', 0, 'business'),
  ('33333333-3333-4333-8333-333333333332', 0, 'business');
INSERT INTO hosted.business_accounts
  (account_id, organization_name, approval_reference,
   purchaser_contact_email, admin_contact_email) VALUES
  ('33333333-3333-4333-8333-333333333331', 'One Studio',
    '33333333-3333-4333-8333-333333333333',
    'buyer@one.example', 'admin@one.example'),
  ('33333333-3333-4333-8333-333333333332', 'Two Studio',
    '33333333-3333-4333-8333-333333333334',
    'buyer@two.example', 'admin@two.example');
INSERT INTO hosted.business_seats
  (account_id, seat_id, worker_contact_email, approval_reference) VALUES
  ('33333333-3333-4333-8333-333333333331',
    '33333333-3333-4333-8333-333333333335',
    'worker@one.example', '33333333-3333-4333-8333-333333333336'),
  ('33333333-3333-4333-8333-333333333331',
    '33333333-3333-4333-8333-333333333337',
    'other@one.example', '33333333-3333-4333-8333-333333333338');
INSERT INTO hosted.vaults (account_id, vault_id) VALUES
  ('33333333-3333-4333-8333-333333333331',
    '33333333-3333-4333-8333-333333333339'),
  ('33333333-3333-4333-8333-333333333332',
    '33333333-3333-4333-8333-33333333333a');
INSERT INTO hosted.business_seat_vaults
  (account_id, seat_id, vault_id) VALUES
  ('33333333-3333-4333-8333-333333333331',
    '33333333-3333-4333-8333-333333333335',
    '33333333-3333-4333-8333-333333333339');
INSERT INTO hosted.business_device_sessions
  (token_hash, account_id, seat_id, vault_id, device_id, expires_at) VALUES
  (repeat('b', 64), '33333333-3333-4333-8333-333333333331',
    '33333333-3333-4333-8333-333333333335',
    '33333333-3333-4333-8333-333333333339',
    '33333333-3333-4333-8333-33333333333b',
    clock_timestamp() + interval '29 days');

DO $$
BEGIN
  BEGIN
    INSERT INTO hosted.business_seat_vaults
      (account_id, seat_id, vault_id) VALUES
      ('33333333-3333-4333-8333-333333333331',
        '33333333-3333-4333-8333-333333333337',
        '33333333-3333-4333-8333-333333333339');
    RAISE EXCEPTION 'one Vault assigned to two seats';
  EXCEPTION WHEN unique_violation THEN NULL; END;

  BEGIN
    INSERT INTO hosted.business_seat_vaults
      (account_id, seat_id, vault_id) VALUES
      ('33333333-3333-4333-8333-333333333331',
        '33333333-3333-4333-8333-333333333335',
        '33333333-3333-4333-8333-33333333333a');
    RAISE EXCEPTION 'cross-company Vault assigned to seat';
  EXCEPTION WHEN foreign_key_violation THEN NULL; END;

  BEGIN
    INSERT INTO hosted.business_device_sessions
      (token_hash, account_id, seat_id, vault_id, device_id, expires_at) VALUES
      (repeat('c', 64), '33333333-3333-4333-8333-333333333331',
        '33333333-3333-4333-8333-333333333337',
        '33333333-3333-4333-8333-333333333339',
        '33333333-3333-4333-8333-33333333333c',
        clock_timestamp() + interval '1 day');
    RAISE EXCEPTION 'device used another seat Vault';
  EXCEPTION WHEN foreign_key_violation THEN NULL; END;

  BEGIN
    INSERT INTO hosted.business_device_sessions
      (token_hash, account_id, seat_id, vault_id, device_id, expires_at) VALUES
      (repeat('d', 64), '33333333-3333-4333-8333-333333333331',
        '33333333-3333-4333-8333-333333333335',
        '33333333-3333-4333-8333-333333333339',
        '33333333-3333-4333-8333-33333333333d',
        clock_timestamp() + interval '31 days');
    RAISE EXCEPTION 'long-lived business bearer accepted';
  EXCEPTION WHEN check_violation THEN NULL; END;
END;
$$;

UPDATE hosted.business_seats SET revoked_at = clock_timestamp()
  WHERE account_id = '33333333-3333-4333-8333-333333333331'
    AND seat_id = '33333333-3333-4333-8333-333333333335';
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM hosted.business_device_sessions
      WHERE token_hash = repeat('b', 64) AND revoked_at IS NOT NULL
  ) THEN RAISE EXCEPTION 'seat revocation left a device active'; END IF;

  BEGIN
    INSERT INTO hosted.business_device_sessions
      (token_hash, account_id, seat_id, vault_id, device_id, expires_at) VALUES
      (repeat('e', 64), '33333333-3333-4333-8333-333333333331',
        '33333333-3333-4333-8333-333333333335',
        '33333333-3333-4333-8333-333333333339',
        '33333333-3333-4333-8333-33333333333e',
        clock_timestamp() + interval '1 day');
    RAISE EXCEPTION 'revoked seat accepted a new device';
  EXCEPTION WHEN raise_exception THEN
    IF SQLERRM != 'hosted_business_seat_unavailable' THEN RAISE; END IF;
  END;

  BEGIN
    UPDATE hosted.business_seats SET revoked_at = NULL
      WHERE account_id = '33333333-3333-4333-8333-333333333331'
        AND seat_id = '33333333-3333-4333-8333-333333333335';
    RAISE EXCEPTION 'revoked seat was reactivated';
  EXCEPTION WHEN raise_exception THEN
    IF SQLERRM != 'hosted_business_seat_revocation_is_final' THEN RAISE; END IF;
  END;
END;
$$;
ROLLBACK;
