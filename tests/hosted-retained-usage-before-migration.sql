-- Disposable PostgreSQL fixture immediately before migration 0028.
INSERT INTO hosted.accounts (account_id, allowance_bytes, retained_bytes)
  VALUES ('99999999-9999-4999-8999-999999999999', 1000, 125);
