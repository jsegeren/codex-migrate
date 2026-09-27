-- A claimed hosted account maps to exactly one recorded Mac-app purchase.
-- The purchase row is historical evidence, not current payment authority:
-- enrollment must still recheck Stripe and prove control of the buyer email.
CREATE TABLE hosted.purchase_enrollments (
  account_id uuid PRIMARY KEY REFERENCES hosted.accounts (account_id),
  purchase_session_id text NOT NULL,
  purchase_mode text NOT NULL CHECK (purchase_mode IN ('sandbox', 'live')),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (purchase_session_id, purchase_mode),
  FOREIGN KEY (purchase_session_id, purchase_mode)
    REFERENCES commerce_purchases (session_id, mode)
);
