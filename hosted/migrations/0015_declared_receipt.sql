-- A missing final receipt page must never look like a complete backup. The
-- first admitted page fixes the client's complete encrypted inventory size;
-- retries must repeat it exactly. These declarations are not storage proof.
ALTER TABLE hosted.upload_reservations
  ADD COLUMN declared_count integer CHECK (declared_count BETWEEN 3 AND 1000000),
  ADD COLUMN declared_bytes bigint CHECK (declared_bytes > 0),
  ADD CONSTRAINT hosted_declared_receipt_pair CHECK (
    (declared_count IS NULL) = (declared_bytes IS NULL));
--> statement-breakpoint
CREATE FUNCTION hosted.append_receipt_page_declared_current(
  p_account_id uuid,
  p_vault_id uuid,
  p_reservation_id uuid,
  p_snapshot_id uuid,
  p_objects jsonb,
  p_expected_count integer,
  p_expected_bytes bigint,
  p_current_allowance bigint
) RETURNS boolean LANGUAGE plpgsql AS $$
BEGIN
  IF p_expected_count IS NULL OR p_expected_count < 3 OR
     p_expected_count > 1000000 OR p_expected_bytes IS NULL OR
     p_expected_bytes < p_expected_count OR
     p_expected_bytes > p_current_allowance THEN
    RAISE EXCEPTION 'hosted_receipt_declaration_invalid';
  END IF;
  -- The old function takes the account then reservation row lock, validates
  -- each claim, and records it atomically. The locks remain held until this
  -- wrapper commits. A conflicting declaration rolls the whole page back.
  PERFORM hosted.append_receipt_page_current(p_account_id, p_vault_id,
    p_reservation_id, p_snapshot_id, p_objects, p_current_allowance);
  UPDATE hosted.upload_reservations SET
    declared_count = coalesce(declared_count, p_expected_count),
    declared_bytes = coalesce(declared_bytes, p_expected_bytes)
    WHERE reservation_id = p_reservation_id AND account_id = p_account_id
      AND vault_id = p_vault_id AND state = 'active'
      AND staged_snapshot_id = p_snapshot_id
      AND (declared_count IS NULL OR declared_count = p_expected_count)
      AND (declared_bytes IS NULL OR declared_bytes = p_expected_bytes)
      AND staged_count <= p_expected_count
      AND staged_bytes <= p_expected_bytes;
  IF NOT FOUND THEN RAISE EXCEPTION 'hosted_receipt_declaration_conflict'; END IF;
  RETURN true;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.append_receipt_page_declared_current(
  uuid, uuid, uuid, uuid, jsonb, integer, bigint, bigint) FROM PUBLIC;
--> statement-breakpoint
CREATE FUNCTION hosted.publish_declared_verified_staged_current(
  p_account_id uuid,
  p_vault_id uuid,
  p_reservation_id uuid,
  p_snapshot_id uuid,
  p_verified_objects jsonb,
  p_current_allowance bigint
) RETURNS boolean LANGUAGE plpgsql AS $$
DECLARE
  v_reservation hosted.upload_reservations%ROWTYPE;
BEGIN
  -- Same account-before-reservation lock order as page admission and the
  -- underlying publication function. No page can change after this check.
  PERFORM 1 FROM hosted.accounts WHERE account_id = p_account_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'hosted_receipt_incomplete'; END IF;
  SELECT * INTO v_reservation FROM hosted.upload_reservations
    WHERE reservation_id = p_reservation_id AND account_id = p_account_id
      AND vault_id = p_vault_id FOR UPDATE;
  IF NOT FOUND OR v_reservation.staged_snapshot_id <> p_snapshot_id OR
     v_reservation.declared_count IS NULL OR
     v_reservation.declared_count <> v_reservation.staged_count OR
     v_reservation.declared_bytes <> v_reservation.staged_bytes THEN
    RAISE EXCEPTION 'hosted_receipt_incomplete';
  END IF;
  RETURN hosted.publish_verified_staged_current(p_account_id, p_vault_id,
    p_reservation_id, p_snapshot_id, p_verified_objects,
    p_current_allowance);
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.publish_declared_verified_staged_current(
  uuid, uuid, uuid, uuid, jsonb, bigint) FROM PUBLIC;
