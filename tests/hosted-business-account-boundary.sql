-- Disposable PostgreSQL after migration 0032. Company rows are inert and
-- cannot inherit an employee's app purchase or device-session authority.
BEGIN;
INSERT INTO commerce_purchases (session_id, mode, release_id, payment_intent, email)
  VALUES ('cs_test_business_boundary', 'sandbox', 'fixture',
    'pi_business_boundary', 'individual@example.test'),
    ('cs_test_business_boundary_other', 'sandbox', 'fixture',
    'pi_business_boundary_other', 'other@example.test');
INSERT INTO hosted.accounts (account_id, allowance_bytes, owner_kind) VALUES
  ('32323232-3232-4232-8232-323232323231', 0, 'individual'),
  ('32323232-3232-4232-8232-323232323232', 0, 'business'),
  ('32323232-3232-4232-8232-323232323237', 0, 'individual');
INSERT INTO hosted.purchase_enrollments
  (account_id, purchase_session_id, purchase_mode) VALUES
  ('32323232-3232-4232-8232-323232323231',
    'cs_test_business_boundary', 'sandbox');
INSERT INTO hosted.business_accounts
  (account_id, organization_name, approval_reference,
   purchaser_contact_email, admin_contact_email) VALUES
  ('32323232-3232-4232-8232-323232323232', 'Example Studio',
    '32323232-3232-4232-8232-323232323233',
    'purchaser@example.test', 'admin@example.test');
INSERT INTO hosted.vaults (account_id, vault_id) VALUES
  ('32323232-3232-4232-8232-323232323232',
    '32323232-3232-4232-8232-323232323234');

DO $$
BEGIN
  BEGIN
    INSERT INTO hosted.purchase_enrollments
      (account_id, purchase_session_id, purchase_mode) VALUES
      ('32323232-3232-4232-8232-323232323232',
        'cs_test_business_boundary_other', 'sandbox');
    RAISE EXCEPTION 'business account inherited individual purchase';
  EXCEPTION WHEN foreign_key_violation THEN NULL; END;

  BEGIN
    INSERT INTO hosted.business_accounts
      (account_id, organization_name, approval_reference,
       purchaser_contact_email, admin_contact_email) VALUES
      ('32323232-3232-4232-8232-323232323231', 'Wrong owner',
        '32323232-3232-4232-8232-323232323235',
        'purchaser@example.test', 'admin@example.test');
    RAISE EXCEPTION 'individual account became a business account';
  EXCEPTION WHEN foreign_key_violation THEN NULL; END;

  BEGIN
    INSERT INTO hosted.device_sessions
      (token_hash, account_id, vault_id, device_id, expires_at) VALUES
      (repeat('a', 64), '32323232-3232-4232-8232-323232323232',
        '32323232-3232-4232-8232-323232323234',
        '32323232-3232-4232-8232-323232323236',
        clock_timestamp() + interval '1 day');
    RAISE EXCEPTION 'business account used individual device session';
  EXCEPTION WHEN foreign_key_violation THEN NULL; END;

  BEGIN
    UPDATE hosted.accounts SET owner_kind = 'business'
      WHERE account_id = '32323232-3232-4232-8232-323232323237';
    RAISE EXCEPTION 'unclaimed account ownership changed in place';
  EXCEPTION WHEN raise_exception THEN
    IF SQLERRM != 'hosted_account_owner_kind_is_immutable' THEN RAISE; END IF;
  END;
END;
$$;
ROLLBACK;
