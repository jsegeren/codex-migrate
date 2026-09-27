-- A hosted history can exceed the web function body limit. Store bounded,
-- idempotent object-claim pages under one reservation. These are untrusted
-- claims, not provider verification or a published backup.
ALTER TABLE hosted.upload_reservations
  ADD COLUMN staged_snapshot_id uuid,
  ADD COLUMN staged_count integer NOT NULL DEFAULT 0
    CHECK (staged_count >= 0 AND staged_count <= 1000000),
  ADD COLUMN staged_bytes bigint NOT NULL DEFAULT 0 CHECK (staged_bytes >= 0);
--> statement-breakpoint
CREATE TABLE hosted.staged_receipt_objects (
  reservation_id uuid NOT NULL REFERENCES hosted.upload_reservations (reservation_id),
  object_key text NOT NULL CHECK (length(object_key) <= 300),
  object_bytes bigint NOT NULL CHECK (object_bytes > 0 AND object_bytes <= 100000000),
  sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  PRIMARY KEY (reservation_id, object_key)
);
--> statement-breakpoint
CREATE FUNCTION hosted.append_receipt_page_current(
  p_account_id uuid,
  p_vault_id uuid,
  p_reservation_id uuid,
  p_snapshot_id uuid,
  p_objects jsonb,
  p_current_allowance bigint
) RETURNS boolean LANGUAGE plpgsql AS $$
DECLARE
  v_prefix text := 'accounts/' || p_account_id::text || '/vaults/' || p_vault_id::text || '/';
  v_reservation hosted.upload_reservations%ROWTYPE;
  v_item jsonb;
  v_key text;
  v_relative text;
  v_bytes bigint;
  v_sha text;
  v_prior hosted.staged_receipt_objects%ROWTYPE;
  v_added_count integer := 0;
  v_added_bytes numeric := 0;
  v_retained bigint;
  v_reserved bigint;
BEGIN
  IF p_account_id IS NULL OR p_vault_id IS NULL OR p_reservation_id IS NULL OR
     p_snapshot_id IS NULL OR p_current_allowance IS NULL OR
     p_current_allowance <= 0 OR jsonb_typeof(p_objects) IS DISTINCT FROM 'array' OR
     jsonb_array_length(p_objects) < 1 OR jsonb_array_length(p_objects) > 512 THEN
    RAISE EXCEPTION 'hosted_receipt_page_invalid';
  END IF;
  -- Same account-before-reservation lock order as publication and grant
  -- issuance. Recheck the fresh Subscription allowance on every page.
  UPDATE hosted.accounts SET allowance_bytes = p_current_allowance
    WHERE account_id = p_account_id
    RETURNING retained_bytes, reserved_bytes INTO v_retained, v_reserved;
  IF NOT FOUND OR v_retained::numeric + v_reserved::numeric >
      p_current_allowance::numeric THEN
    RAISE EXCEPTION 'hosted_receipt_page_invalid';
  END IF;
  SELECT * INTO v_reservation FROM hosted.upload_reservations
    WHERE reservation_id = p_reservation_id AND account_id = p_account_id
      AND vault_id = p_vault_id FOR UPDATE;
  IF NOT FOUND OR v_reservation.state <> 'active' OR
     v_reservation.expires_at <= clock_timestamp() OR
     (v_reservation.staged_snapshot_id IS NOT NULL AND
      v_reservation.staged_snapshot_id <> p_snapshot_id) THEN
    RAISE EXCEPTION 'hosted_receipt_page_invalid';
  END IF;
  IF v_reservation.staged_snapshot_id IS NULL THEN
    UPDATE hosted.upload_reservations SET staged_snapshot_id = p_snapshot_id
      WHERE reservation_id = p_reservation_id;
  END IF;

  FOR v_item IN SELECT value FROM jsonb_array_elements(p_objects) LOOP
    IF jsonb_typeof(v_item) <> 'object' OR
       NOT (v_item ?& ARRAY['key', 'bytes', 'sha256']) OR
       v_item - 'key' - 'bytes' - 'sha256' <> '{}'::jsonb OR
       jsonb_typeof(v_item->'key') <> 'string' OR
       jsonb_typeof(v_item->'bytes') <> 'number' OR
       jsonb_typeof(v_item->'sha256') <> 'string' OR
       (v_item->>'bytes') !~ '^[1-9][0-9]*$' THEN
      RAISE EXCEPTION 'hosted_receipt_page_invalid';
    END IF;
    v_key := v_item->>'key';
    v_sha := v_item->>'sha256';
    IF length(v_key) > 300 OR left(v_key, length(v_prefix)) <> v_prefix OR
       v_sha !~ '^[0-9a-f]{64}$' THEN
      RAISE EXCEPTION 'hosted_receipt_page_invalid';
    END IF;
    BEGIN
      v_bytes := (v_item->>'bytes')::bigint;
    EXCEPTION WHEN numeric_value_out_of_range THEN
      RAISE EXCEPTION 'hosted_receipt_page_invalid';
    END;
    IF v_bytes <= 0 OR v_bytes > 100000000 THEN
      RAISE EXCEPTION 'hosted_receipt_page_invalid';
    END IF;
    v_relative := substring(v_key from length(v_prefix) + 1);
    IF NOT (v_relative = 'metadata/' || p_snapshot_id || '.json' AND v_bytes <= 1048576 OR
            v_relative = 'manifests/' || p_snapshot_id || '.cvmanifest' OR
            v_relative = 'refs/' || p_snapshot_id || '.json' AND v_bytes <= 1048576 OR
            v_relative ~ '^objects/[0-9a-f]{2}/[0-9a-f]{62}\.cvchunk$' AND
              v_bytes <= 67109888) THEN
      RAISE EXCEPTION 'hosted_receipt_page_invalid';
    END IF;
    INSERT INTO hosted.staged_receipt_objects
      (reservation_id, object_key, object_bytes, sha256)
      VALUES (p_reservation_id, v_key, v_bytes, v_sha)
      ON CONFLICT DO NOTHING;
    IF FOUND THEN
      v_added_count := v_added_count + 1;
      v_added_bytes := v_added_bytes + v_bytes;
    ELSE
      SELECT * INTO v_prior FROM hosted.staged_receipt_objects
        WHERE reservation_id = p_reservation_id AND object_key = v_key;
      IF NOT FOUND OR v_prior.object_bytes <> v_bytes OR v_prior.sha256 <> v_sha THEN
        RAISE EXCEPTION 'hosted_receipt_page_conflict';
      END IF;
    END IF;
  END LOOP;
  IF v_reservation.staged_count::numeric + v_added_count > 1000000 OR
     v_reservation.staged_bytes::numeric + v_added_bytes >
       p_current_allowance::numeric THEN
    RAISE EXCEPTION 'hosted_receipt_page_over_quota';
  END IF;
  UPDATE hosted.upload_reservations SET
    staged_count = staged_count + v_added_count,
    staged_bytes = staged_bytes + v_added_bytes::bigint
    WHERE reservation_id = p_reservation_id;
  RETURN true;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.append_receipt_page_current(
  uuid, uuid, uuid, uuid, jsonb, bigint
) FROM PUBLIC;
