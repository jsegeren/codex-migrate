-- Provider-checked objects can be recorded in bounded transactions. An ACK
-- here is not a published backup. The service must call this only after R2
-- independently confirms every exact key, byte count and SHA-256 in the page.
CREATE TABLE hosted.verified_receipt_objects (
  reservation_id uuid NOT NULL,
  object_key text NOT NULL,
  object_bytes bigint NOT NULL CHECK (object_bytes > 0),
  sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  verified_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (reservation_id, object_key),
  FOREIGN KEY (reservation_id, object_key)
    REFERENCES hosted.staged_receipt_objects (reservation_id, object_key)
);
--> statement-breakpoint
CREATE FUNCTION hosted.record_verified_receipt_page_current(
  p_account_id uuid,
  p_vault_id uuid,
  p_reservation_id uuid,
  p_snapshot_id uuid,
  p_verified_objects jsonb,
  p_current_allowance bigint
) RETURNS integer LANGUAGE plpgsql AS $$
DECLARE
  v_reservation hosted.upload_reservations%ROWTYPE;
  v_item jsonb;
  v_key text;
  v_bytes bigint;
  v_sha text;
  v_staged hosted.staged_receipt_objects%ROWTYPE;
  v_retained bigint;
  v_reserved bigint;
BEGIN
  IF p_account_id IS NULL OR p_vault_id IS NULL OR p_reservation_id IS NULL OR
     p_snapshot_id IS NULL OR p_current_allowance IS NULL OR
     p_current_allowance <= 0 OR
     jsonb_typeof(p_verified_objects) IS DISTINCT FROM 'array' OR
     jsonb_array_length(p_verified_objects) < 1 OR
     jsonb_array_length(p_verified_objects) > 128 THEN
    RAISE EXCEPTION 'hosted_verified_page_invalid';
  END IF;
  -- Same account-before-reservation lock order as page admission and publish.
  UPDATE hosted.accounts SET allowance_bytes = p_current_allowance
    WHERE account_id = p_account_id
    RETURNING retained_bytes, reserved_bytes INTO v_retained, v_reserved;
  IF NOT FOUND OR v_retained::numeric + v_reserved::numeric >
      p_current_allowance::numeric THEN
    RAISE EXCEPTION 'hosted_verified_page_invalid';
  END IF;
  SELECT * INTO v_reservation FROM hosted.upload_reservations
    WHERE reservation_id = p_reservation_id AND account_id = p_account_id
      AND vault_id = p_vault_id FOR UPDATE;
  IF NOT FOUND OR v_reservation.state <> 'active' OR
     v_reservation.expires_at <= clock_timestamp() OR
     v_reservation.staged_snapshot_id <> p_snapshot_id OR
     v_reservation.declared_count IS NULL OR
     v_reservation.declared_count <> v_reservation.staged_count OR
     v_reservation.declared_bytes <> v_reservation.staged_bytes THEN
    RAISE EXCEPTION 'hosted_verified_page_invalid';
  END IF;
  FOR v_item IN SELECT value FROM jsonb_array_elements(p_verified_objects) LOOP
    IF jsonb_typeof(v_item) <> 'object' OR
       NOT (v_item ?& ARRAY['key', 'bytes', 'sha256']) OR
       v_item - 'key' - 'bytes' - 'sha256' <> '{}'::jsonb OR
       jsonb_typeof(v_item->'key') <> 'string' OR
       jsonb_typeof(v_item->'bytes') <> 'number' OR
       jsonb_typeof(v_item->'sha256') <> 'string' OR
       (v_item->>'bytes') !~ '^[1-9][0-9]*$' OR
       (v_item->>'sha256') !~ '^[0-9a-f]{64}$' THEN
      RAISE EXCEPTION 'hosted_verified_page_invalid';
    END IF;
    v_key := v_item->>'key';
    v_sha := v_item->>'sha256';
    BEGIN
      v_bytes := (v_item->>'bytes')::bigint;
    EXCEPTION WHEN numeric_value_out_of_range THEN
      RAISE EXCEPTION 'hosted_verified_page_invalid';
    END;
    SELECT * INTO v_staged FROM hosted.staged_receipt_objects
      WHERE reservation_id = p_reservation_id AND object_key = v_key;
    IF NOT FOUND OR v_staged.object_bytes <> v_bytes OR
       v_staged.sha256 <> v_sha THEN
      RAISE EXCEPTION 'hosted_verified_page_conflict';
    END IF;
    INSERT INTO hosted.verified_receipt_objects
      (reservation_id, object_key, object_bytes, sha256)
      VALUES (p_reservation_id, v_key, v_bytes, v_sha)
      ON CONFLICT (reservation_id, object_key) DO UPDATE SET
        verified_at = clock_timestamp()
      WHERE hosted.verified_receipt_objects.object_bytes = EXCLUDED.object_bytes
        AND hosted.verified_receipt_objects.sha256 = EXCLUDED.sha256;
    IF NOT FOUND THEN RAISE EXCEPTION 'hosted_verified_page_conflict'; END IF;
  END LOOP;
  RETURN jsonb_array_length(p_verified_objects);
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.record_verified_receipt_page_current(
  uuid, uuid, uuid, uuid, jsonb, bigint) FROM PUBLIC;
--> statement-breakpoint
CREATE FUNCTION hosted.publish_checkpointed_staged_current(
  p_account_id uuid,
  p_vault_id uuid,
  p_reservation_id uuid,
  p_snapshot_id uuid,
  p_current_allowance bigint
) RETURNS boolean LANGUAGE plpgsql AS $$
DECLARE
  v_reservation hosted.upload_reservations%ROWTYPE;
  v_count bigint;
  v_bytes numeric;
  v_verified jsonb;
BEGIN
  IF p_account_id IS NULL OR p_vault_id IS NULL OR p_reservation_id IS NULL OR
     p_snapshot_id IS NULL OR p_current_allowance IS NULL OR
     p_current_allowance <= 0 THEN
    RAISE EXCEPTION 'hosted_checkpoint_publication_invalid';
  END IF;
  PERFORM 1 FROM hosted.accounts WHERE account_id = p_account_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'hosted_checkpoint_publication_invalid'; END IF;
  SELECT * INTO v_reservation FROM hosted.upload_reservations
    WHERE reservation_id = p_reservation_id AND account_id = p_account_id
      AND vault_id = p_vault_id FOR UPDATE;
  IF NOT FOUND OR v_reservation.state NOT IN ('active', 'published') OR
     (v_reservation.state = 'active' AND
      v_reservation.expires_at <= clock_timestamp()) OR
     v_reservation.staged_snapshot_id <> p_snapshot_id OR
     v_reservation.declared_count IS NULL OR
     v_reservation.declared_count <> v_reservation.staged_count OR
     v_reservation.declared_bytes <> v_reservation.staged_bytes THEN
    RAISE EXCEPTION 'hosted_checkpoint_publication_invalid';
  END IF;
  -- A lost success response may be retried long after the 24-hour proof
  -- window. The prior publication is immutable; do not require a second R2
  -- scan just to confirm its exact already-published reservation and snapshot.
  IF v_reservation.state = 'published' THEN
    RETURN EXISTS (SELECT 1 FROM hosted.snapshots
      WHERE account_id = p_account_id AND vault_id = p_vault_id
        AND reservation_id = p_reservation_id AND snapshot_id = p_snapshot_id
        AND verified_object_count = v_reservation.staged_count);
  END IF;
  SELECT count(*), coalesce(sum(object_bytes), 0) INTO v_count, v_bytes
    FROM hosted.verified_receipt_objects
    WHERE reservation_id = p_reservation_id AND
      verified_at >= clock_timestamp() - interval '24 hours';
  IF v_count <> v_reservation.staged_count OR
     v_bytes <> v_reservation.staged_bytes OR EXISTS (
      SELECT object_key, object_bytes, sha256
        FROM hosted.staged_receipt_objects
        WHERE reservation_id = p_reservation_id
      EXCEPT
      SELECT object_key, object_bytes, sha256
        FROM hosted.verified_receipt_objects
        WHERE reservation_id = p_reservation_id AND
          verified_at >= clock_timestamp() - interval '24 hours'
    ) THEN
    RAISE EXCEPTION 'hosted_checkpoint_publication_incomplete';
  END IF;
  SELECT jsonb_agg(jsonb_build_object('key', object_key, 'bytes', object_bytes,
      'sha256', sha256) ORDER BY object_key) INTO v_verified
    FROM hosted.verified_receipt_objects
    WHERE reservation_id = p_reservation_id;
  RETURN hosted.publish_declared_verified_staged_current(p_account_id,
    p_vault_id, p_reservation_id, p_snapshot_id, v_verified,
    p_current_allowance);
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.publish_checkpointed_staged_current(
  uuid, uuid, uuid, uuid, bigint) FROM PUBLIC;
