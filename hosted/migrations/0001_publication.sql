-- The service calls this only with the immutable object list returned by its
-- provider-backed verifier. SQL cannot turn a client receipt into storage proof.
CREATE TABLE hosted.objects (
  account_id uuid NOT NULL,
  vault_id uuid NOT NULL,
  object_key text NOT NULL,
  bytes bigint NOT NULL CHECK (bytes > 0),
  sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  PRIMARY KEY (account_id, vault_id, object_key),
  FOREIGN KEY (account_id, vault_id) REFERENCES hosted.vaults (account_id, vault_id)
);
--> statement-breakpoint
CREATE TABLE hosted.snapshots (
  account_id uuid NOT NULL,
  vault_id uuid NOT NULL,
  snapshot_id uuid NOT NULL,
  reservation_id uuid NOT NULL UNIQUE REFERENCES hosted.upload_reservations (reservation_id),
  verified_object_count integer NOT NULL CHECK (verified_object_count >= 3),
  published_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (account_id, vault_id, snapshot_id),
  FOREIGN KEY (account_id, vault_id) REFERENCES hosted.vaults (account_id, vault_id)
);
--> statement-breakpoint
CREATE TABLE hosted.snapshot_objects (
  account_id uuid NOT NULL,
  vault_id uuid NOT NULL,
  snapshot_id uuid NOT NULL,
  object_key text NOT NULL,
  PRIMARY KEY (account_id, vault_id, snapshot_id, object_key),
  FOREIGN KEY (account_id, vault_id, snapshot_id)
    REFERENCES hosted.snapshots (account_id, vault_id, snapshot_id),
  FOREIGN KEY (account_id, vault_id, object_key)
    REFERENCES hosted.objects (account_id, vault_id, object_key)
);
--> statement-breakpoint
ALTER TABLE hosted.vaults ADD COLUMN last_good_snapshot_id uuid;
--> statement-breakpoint
ALTER TABLE hosted.vaults ADD CONSTRAINT vault_last_good_snapshot_fk
  FOREIGN KEY (account_id, vault_id, last_good_snapshot_id)
  REFERENCES hosted.snapshots (account_id, vault_id, snapshot_id);
--> statement-breakpoint
CREATE FUNCTION hosted.publish_verified_snapshot(
  p_account_id uuid,
  p_vault_id uuid,
  p_reservation_id uuid,
  p_snapshot_id uuid,
  p_verified_objects jsonb
) RETURNS boolean LANGUAGE plpgsql AS $$
DECLARE
  v_allowance bigint;
  v_retained bigint;
  v_reserved bigint;
  v_reservation hosted.upload_reservations%ROWTYPE;
  v_existing hosted.snapshots%ROWTYPE;
  v_item jsonb;
  v_key text;
  v_relative_key text;
  v_bytes bigint;
  v_count integer;
  v_prefix text := 'accounts/' || p_account_id || '/vaults/' || p_vault_id || '/';
  v_metadata boolean := false;
  v_manifest boolean := false;
  v_reference boolean := false;
  v_added numeric;
BEGIN
  IF p_account_id IS NULL OR p_vault_id IS NULL OR
     p_reservation_id IS NULL OR p_snapshot_id IS NULL OR
     jsonb_typeof(p_verified_objects) IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'hosted_publication_invalid';
  END IF;
  v_count := jsonb_array_length(p_verified_objects);
  IF v_count < 3 OR v_count > 1000000 THEN
    RAISE EXCEPTION 'hosted_publication_invalid';
  END IF;

  -- This one account lock serializes publication and reservations across all
  -- of its Vaults. It also prevents an older retry from moving the pointer.
  SELECT allowance_bytes, retained_bytes, reserved_bytes
    INTO v_allowance, v_retained, v_reserved
    FROM hosted.accounts WHERE account_id = p_account_id FOR UPDATE;
  IF NOT FOUND OR NOT EXISTS (SELECT 1 FROM hosted.vaults
      WHERE account_id = p_account_id AND vault_id = p_vault_id) THEN
    RAISE EXCEPTION 'hosted_publication_invalid';
  END IF;

  -- A completed retry is harmless only if it describes exactly the same
  -- snapshot and verified object set. Do not change a newer last-good pointer.
  SELECT * INTO v_existing FROM hosted.snapshots
    WHERE account_id = p_account_id AND vault_id = p_vault_id
      AND snapshot_id = p_snapshot_id;
  IF FOUND THEN
    IF v_existing.reservation_id <> p_reservation_id OR
       v_existing.verified_object_count <> v_count OR EXISTS (
         SELECT item.key, item.bytes, item.sha256
           FROM jsonb_to_recordset(p_verified_objects)
             AS item(key text, bytes bigint, sha256 text)
         EXCEPT
         SELECT object_key, bytes, sha256 FROM hosted.objects o
           JOIN hosted.snapshot_objects so USING (account_id, vault_id, object_key)
           WHERE so.account_id = p_account_id AND so.vault_id = p_vault_id
             AND so.snapshot_id = p_snapshot_id
       ) OR EXISTS (
         SELECT object_key, bytes, sha256 FROM hosted.objects o
           JOIN hosted.snapshot_objects so USING (account_id, vault_id, object_key)
           WHERE so.account_id = p_account_id AND so.vault_id = p_vault_id
             AND so.snapshot_id = p_snapshot_id
         EXCEPT
         SELECT item.key, item.bytes, item.sha256
           FROM jsonb_to_recordset(p_verified_objects)
             AS item(key text, bytes bigint, sha256 text)
       ) THEN
      RAISE EXCEPTION 'hosted_publication_conflict';
    END IF;
    RETURN true;
  END IF;

  SELECT * INTO v_reservation FROM hosted.upload_reservations
    WHERE reservation_id = p_reservation_id AND account_id = p_account_id
      AND vault_id = p_vault_id FOR UPDATE;
  IF NOT FOUND OR v_reservation.state <> 'active' OR
     v_reservation.expires_at <= clock_timestamp() OR
     v_reserved < v_reservation.reserved_bytes THEN
    RAISE EXCEPTION 'hosted_publication_invalid';
  END IF;

  -- Defence in depth. The trusted service must have already independently
  -- checked every exact scoped key, length, and SHA-256 with the provider.
  FOR v_item IN SELECT value FROM jsonb_array_elements(p_verified_objects) LOOP
    IF jsonb_typeof(v_item) <> 'object' OR
       NOT (v_item ?& ARRAY['key', 'bytes', 'sha256']) OR
       v_item - 'key' - 'bytes' - 'sha256' <> '{}'::jsonb OR
       jsonb_typeof(v_item->'key') <> 'string' OR
       jsonb_typeof(v_item->'bytes') <> 'number' OR
       jsonb_typeof(v_item->'sha256') <> 'string' THEN
      RAISE EXCEPTION 'hosted_publication_invalid';
    END IF;
    v_key := v_item->>'key';
    IF left(v_key, length(v_prefix)) <> v_prefix OR
       (v_item->>'bytes') !~ '^[1-9][0-9]*$' OR
       (v_item->>'sha256') !~ '^[0-9a-f]{64}$' THEN
      RAISE EXCEPTION 'hosted_publication_invalid';
    END IF;
    BEGIN
      v_bytes := (v_item->>'bytes')::bigint;
    EXCEPTION WHEN numeric_value_out_of_range THEN
      RAISE EXCEPTION 'hosted_publication_invalid';
    END;
    v_relative_key := substring(v_key from length(v_prefix) + 1);
    IF v_relative_key = 'metadata/' || p_snapshot_id || '.json' AND
       v_bytes <= 1048576 THEN
      v_metadata := true;
    ELSIF v_relative_key = 'manifests/' || p_snapshot_id || '.cvmanifest' AND
          v_bytes <= 134218752 THEN
      v_manifest := true;
    ELSIF v_relative_key = 'refs/' || p_snapshot_id || '.json' AND
          v_bytes <= 1048576 THEN
      v_reference := true;
    ELSIF v_relative_key ~ '^objects/[0-9a-f]{2}/[0-9a-f]{62}\.cvchunk$' AND
          v_bytes <= 67109888 THEN
      NULL;
    ELSE
      RAISE EXCEPTION 'hosted_publication_invalid';
    END IF;
  END LOOP;
  IF NOT (v_metadata AND v_manifest AND v_reference) OR
     (SELECT count(DISTINCT item.key) FROM jsonb_to_recordset(p_verified_objects)
       AS item(key text)) <> v_count THEN
    RAISE EXCEPTION 'hosted_publication_invalid';
  END IF;

  IF EXISTS (
    SELECT 1 FROM jsonb_to_recordset(p_verified_objects)
      AS item(key text, bytes bigint, sha256 text)
    JOIN hosted.objects o ON o.account_id = p_account_id AND
      o.vault_id = p_vault_id AND o.object_key = item.key
    WHERE o.bytes <> item.bytes OR o.sha256 <> item.sha256
  ) THEN RAISE EXCEPTION 'hosted_publication_conflict'; END IF;

  SELECT coalesce(sum(item.bytes), 0) INTO v_added
    FROM jsonb_to_recordset(p_verified_objects)
      AS item(key text, bytes bigint, sha256 text)
    LEFT JOIN hosted.objects o ON o.account_id = p_account_id AND
      o.vault_id = p_vault_id AND o.object_key = item.key
    WHERE o.object_key IS NULL;
  IF v_added > v_reservation.reserved_bytes OR
     v_retained::numeric + v_reserved::numeric > v_allowance::numeric THEN
    RAISE EXCEPTION 'hosted_publication_over_quota';
  END IF;

  INSERT INTO hosted.objects (account_id, vault_id, object_key, bytes, sha256)
    SELECT p_account_id, p_vault_id, item.key, item.bytes, item.sha256
      FROM jsonb_to_recordset(p_verified_objects)
        AS item(key text, bytes bigint, sha256 text)
      LEFT JOIN hosted.objects o ON o.account_id = p_account_id AND
        o.vault_id = p_vault_id AND o.object_key = item.key
      WHERE o.object_key IS NULL;
  INSERT INTO hosted.snapshots
    (account_id, vault_id, snapshot_id, reservation_id, verified_object_count)
    VALUES (p_account_id, p_vault_id, p_snapshot_id, p_reservation_id, v_count);
  INSERT INTO hosted.snapshot_objects
    (account_id, vault_id, snapshot_id, object_key)
    SELECT p_account_id, p_vault_id, p_snapshot_id, item.key
      FROM jsonb_to_recordset(p_verified_objects) AS item(key text);

  UPDATE hosted.accounts SET retained_bytes = retained_bytes + v_added::bigint,
    reserved_bytes = reserved_bytes - v_reservation.reserved_bytes
    WHERE account_id = p_account_id;
  UPDATE hosted.upload_reservations SET state = 'published'
    WHERE reservation_id = p_reservation_id;
  UPDATE hosted.vaults SET last_good_snapshot_id = p_snapshot_id
    WHERE account_id = p_account_id AND vault_id = p_vault_id;
  RETURN true;
END;
$$;
--> statement-breakpoint
REVOKE EXECUTE ON FUNCTION hosted.publish_verified_snapshot(uuid, uuid, uuid, uuid, jsonb)
  FROM PUBLIC;
