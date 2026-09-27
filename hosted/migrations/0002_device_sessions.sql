-- A paid download link cannot authorize storage. Session creation is a
-- separate authenticated enrollment step; only its digest is retained here.
CREATE TABLE hosted.device_sessions (
  token_hash text PRIMARY KEY CHECK (token_hash ~ '^[0-9a-f]{64}$'),
  account_id uuid NOT NULL,
  vault_id uuid NOT NULL,
  device_id uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  FOREIGN KEY (account_id, vault_id) REFERENCES hosted.vaults (account_id, vault_id),
  CHECK (expires_at > created_at AND expires_at <= created_at + interval '30 days'),
  CHECK (revoked_at IS NULL OR revoked_at >= created_at)
);
--> statement-breakpoint
CREATE INDEX hosted_device_sessions_account_idx
  ON hosted.device_sessions (account_id, vault_id);
