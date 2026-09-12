CREATE TABLE commerce_checkout_recoveries (
  session_id text NOT NULL,
  mode text NOT NULL CHECK (mode IN ('sandbox', 'live')),
  email text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  mail_state text NOT NULL DEFAULT 'pending' CHECK (mail_state IN ('pending', 'sending', 'sent', 'uncertain')),
  mail_attempts integer NOT NULL DEFAULT 0,
  mail_lease uuid,
  mail_started_at timestamptz,
  PRIMARY KEY (session_id, mode)
);
