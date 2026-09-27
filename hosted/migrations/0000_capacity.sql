CREATE SCHEMA hosted;
--> statement-breakpoint
CREATE TABLE hosted.accounts (
  account_id uuid PRIMARY KEY,
  allowance_bytes bigint NOT NULL CHECK (allowance_bytes > 0),
  retained_bytes bigint NOT NULL DEFAULT 0 CHECK (retained_bytes >= 0),
  reserved_bytes bigint NOT NULL DEFAULT 0 CHECK (reserved_bytes >= 0)
);
--> statement-breakpoint
CREATE TABLE hosted.vaults (
  account_id uuid NOT NULL REFERENCES hosted.accounts (account_id),
  vault_id uuid NOT NULL,
  PRIMARY KEY (account_id, vault_id)
);
--> statement-breakpoint
CREATE TABLE hosted.upload_reservations (
  reservation_id uuid PRIMARY KEY,
  account_id uuid NOT NULL,
  vault_id uuid NOT NULL,
  reserved_bytes bigint NOT NULL CHECK (reserved_bytes > 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  state text NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'cleanup_pending', 'released', 'published')),
  FOREIGN KEY (account_id, vault_id) REFERENCES hosted.vaults (account_id, vault_id),
  CHECK (expires_at > created_at)
);
--> statement-breakpoint
CREATE FUNCTION hosted.reserve_upload(
  p_account_id uuid,
  p_vault_id uuid,
  p_reservation_id uuid,
  p_bytes bigint,
  p_expires_at timestamptz
) RETURNS boolean LANGUAGE plpgsql AS $$
BEGIN
  IF p_bytes IS NULL OR p_bytes <= 0 OR p_expires_at IS NULL OR
     p_expires_at <= now() OR p_expires_at > now() + interval '1 hour' OR
     NOT EXISTS (SELECT 1 FROM hosted.vaults
       WHERE account_id = p_account_id AND vault_id = p_vault_id) THEN
    RETURN false;
  END IF;

  -- This single row update serializes grants across every Vault on the
  -- account. Numeric arithmetic keeps a downgraded/over-limit row from
  -- overflowing before the predicate can reject it.
  UPDATE hosted.accounts
     SET reserved_bytes = reserved_bytes + p_bytes
   WHERE account_id = p_account_id
     AND p_bytes::numeric <= allowance_bytes::numeric -
       retained_bytes::numeric - reserved_bytes::numeric;
  IF NOT FOUND THEN RETURN false; END IF;

  -- A duplicate reservation ID or deleted Vault aborts this transaction,
  -- rolling back the preceding quota update. Expiry never releases bytes by
  -- itself: storage cleanup must be proven before a release is permitted.
  INSERT INTO hosted.upload_reservations
    (reservation_id, account_id, vault_id, reserved_bytes, expires_at)
  VALUES (p_reservation_id, p_account_id, p_vault_id, p_bytes, p_expires_at);
  RETURN true;
END;
$$;
