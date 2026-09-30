-- Disposable database after migration 0037. A paired seat still has no
-- storage allowance until a separate, time-bounded operator approval exists.
BEGIN;
INSERT INTO hosted.accounts (account_id, allowance_bytes, owner_kind)
  VALUES ('77777777-7777-4777-8777-777777777771', 0, 'business');
INSERT INTO hosted.business_accounts
  (account_id, organization_name, approval_reference,
   purchaser_contact_email, admin_contact_email) VALUES
  ('77777777-7777-4777-8777-777777777771', 'Entitlement Test',
   '77777777-7777-4777-8777-777777777772',
   'buyer@example.test', 'admin@example.test');

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM hosted.business_backup_entitlements
      WHERE account_id = '77777777-7777-4777-8777-777777777771') THEN
    RAISE EXCEPTION 'business account started with storage entitlement'; END IF;
  BEGIN
    INSERT INTO hosted.business_backup_entitlements
      (entitlement_id, account_id, approval_reference, allowance_bytes,
       starts_at, expires_at)
      VALUES ('77777777-7777-4777-8777-777777777774',
        '77777777-7777-4777-8777-777777777771',
        '77777777-7777-4777-8777-777777777773', 0,
        clock_timestamp(), clock_timestamp() + interval '1 day');
    RAISE EXCEPTION 'zero allowance accepted';
  EXCEPTION WHEN check_violation THEN NULL; END;
  BEGIN
    INSERT INTO hosted.business_backup_entitlements
      (entitlement_id, account_id, approval_reference, allowance_bytes,
       starts_at, expires_at)
      VALUES ('77777777-7777-4777-8777-777777777774',
        '77777777-7777-4777-8777-777777777771',
        '77777777-7777-4777-8777-777777777773', 1000000,
        clock_timestamp(), clock_timestamp() + interval '91 days');
    RAISE EXCEPTION 'overlong pilot accepted';
  EXCEPTION WHEN check_violation THEN NULL; END;
END;
$$;

INSERT INTO hosted.business_backup_entitlements
  (entitlement_id, account_id, approval_reference, allowance_bytes,
   starts_at, expires_at)
  VALUES ('77777777-7777-4777-8777-777777777774',
    '77777777-7777-4777-8777-777777777771',
    '77777777-7777-4777-8777-777777777773', 1000000,
    clock_timestamp() - interval '1 minute',
    clock_timestamp() + interval '1 day');
DO $$
BEGIN
  IF (SELECT allowance_bytes FROM hosted.business_backup_entitlements
      WHERE account_id = '77777777-7777-4777-8777-777777777771'
        AND revoked_at IS NULL AND starts_at <= clock_timestamp()
        AND expires_at > clock_timestamp()) IS DISTINCT FROM 1000000 THEN
    RAISE EXCEPTION 'approved allowance unavailable'; END IF;
  BEGIN
    UPDATE hosted.business_backup_entitlements SET allowance_bytes = 2000000
      WHERE account_id = '77777777-7777-4777-8777-777777777771';
    RAISE EXCEPTION 'allowance changed without a new approval';
  EXCEPTION WHEN raise_exception THEN
    IF SQLERRM <> 'hosted_business_entitlement_history_is_immutable' THEN
      RAISE; END IF;
  END;
  BEGIN
    INSERT INTO hosted.business_backup_entitlements
      (entitlement_id, account_id, approval_reference, allowance_bytes,
       starts_at, expires_at)
      VALUES ('77777777-7777-4777-8777-777777777775',
        '77777777-7777-4777-8777-777777777771',
        '77777777-7777-4777-8777-777777777776', 2000000,
        clock_timestamp(), clock_timestamp() + interval '1 day');
    RAISE EXCEPTION 'overlapping current allowance accepted';
  EXCEPTION WHEN unique_violation THEN NULL; END;
END;
$$;
UPDATE hosted.business_backup_entitlements SET revoked_at = clock_timestamp()
  WHERE account_id = '77777777-7777-4777-8777-777777777771';
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM hosted.business_backup_entitlements
      WHERE account_id = '77777777-7777-4777-8777-777777777771'
        AND revoked_at IS NULL AND starts_at <= clock_timestamp()
        AND expires_at > clock_timestamp()) THEN
    RAISE EXCEPTION 'revoked entitlement remained active'; END IF;
  BEGIN
    UPDATE hosted.business_backup_entitlements SET revoked_at = NULL
      WHERE account_id = '77777777-7777-4777-8777-777777777771';
    RAISE EXCEPTION 'revocation reversed';
  EXCEPTION WHEN raise_exception THEN
    IF SQLERRM <> 'hosted_business_entitlement_history_is_immutable' THEN
      RAISE; END IF;
  END;
END;
$$;
INSERT INTO hosted.business_backup_entitlements
  (entitlement_id, account_id, approval_reference, allowance_bytes,
   starts_at, expires_at)
  VALUES ('77777777-7777-4777-8777-777777777775',
    '77777777-7777-4777-8777-777777777771',
    '77777777-7777-4777-8777-777777777776', 2000000,
    clock_timestamp(), clock_timestamp() + interval '1 day');
DO $$
BEGIN
  IF (SELECT count(*) FROM hosted.business_backup_entitlements
      WHERE account_id = '77777777-7777-4777-8777-777777777771') != 2 THEN
    RAISE EXCEPTION 'renewal erased prior approval'; END IF;
END;
$$;
ROLLBACK;
