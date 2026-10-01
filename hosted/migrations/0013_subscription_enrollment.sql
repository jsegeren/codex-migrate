-- A hosted subscription is a separate, explicit enrollment after the Mac-app
-- purchase. This table is evidence to recheck against Stripe, never payment
-- authority by itself. No checkout or insertion path is activated here.
ALTER TABLE hosted.purchase_enrollments
  ADD CONSTRAINT hosted_purchase_account_mode_unique
  UNIQUE (account_id, purchase_mode);
--> statement-breakpoint
CREATE TABLE hosted.subscription_enrollments (
  account_id uuid PRIMARY KEY,
  mode text NOT NULL CHECK (mode IN ('sandbox', 'live')),
  subscription_id text NOT NULL CHECK (subscription_id ~ '^sub_[A-Za-z0-9]+$'),
  customer_id text NOT NULL CHECK (customer_id ~ '^cus_[A-Za-z0-9]+$'),
  price_id text NOT NULL CHECK (price_id ~ '^price_[A-Za-z0-9]+$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (account_id, mode)
    REFERENCES hosted.purchase_enrollments (account_id, purchase_mode),
  UNIQUE (mode, subscription_id)
);
