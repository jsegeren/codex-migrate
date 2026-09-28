"""One-off synthetic Vault recovery proof across two independent macOS runners.

The artifact contains only a disposable test key and synthetic ciphertext. Never
print the recovery key, helper output, or Keychain contents.
"""

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from codex_migrate.errors import MigrationError
from codex_migrate.vault import markdown_chunks, read_thread_page, search
from codex_migrate.vault_backup import backup
from codex_migrate.vault_history import search_titles
from codex_migrate.vault_recovery import (
    import_recovery_key, restore_snapshot, snapshot_catalog, verify_snapshot,
)


TRANSCRIPT = b'{"type":"response_item","payload":{"content":"portable synthetic work"}}\n'
RELATIVE = Path("sessions/2026/09/24/portable.jsonl")
DATABASE_THREAD = "44444444-4444-4444-8444-444444444444"
DATABASE_TEXT = "portable synthetic database-only turn"
DATABASE_TITLE = "portable state-only original title"
DATABASE_NAME = "portable state-only current name"
PARENT_THREAD = "11111111-1111-4111-8111-111111111111"
CHILD_THREAD = "22222222-2222-4222-8222-222222222222"
INHERITED_TEXT = "portable inherited database-only turn"
PARENT_LATER_TEXT = "portable excluded parent-only turn"
CHILD_TEXT = "portable child-local database turn"
EMPTY_PARENT_THREAD = "55555555-5555-4555-8555-555555555555"
ONLY_CHILD_THREAD = "66666666-6666-4666-8666-666666666666"
ONLY_CHILD_TEXT = "portable child with no parent database rows"


def write_fork_rollouts(codex: Path) -> None:
    def record(ordinal: int, kind: str, payload: dict) -> str:
        return json.dumps({"ordinal": ordinal, "type": kind, "payload": payload}) + "\n"

    archived = codex / "archived_sessions"
    archived.mkdir()
    parent_prefix = (record(0, "session_meta", {"id": PARENT_THREAD})
                     + record(1, "event_msg", {"event": "metadata"}))
    (archived / ("rollout-" + PARENT_THREAD + ".jsonl")).write_text(
        parent_prefix + record(2, "event_msg", {"event": "later metadata"}))
    child = codex / "sessions/2026/09/24" / ("rollout-" + CHILD_THREAD + ".jsonl")
    child.write_text(record(2, "session_meta", {"id": CHILD_THREAD,
                                                "history_base": {
        "thread_id": PARENT_THREAD, "end_ordinal_exclusive": 2,
        "end_byte_offset": len(parent_prefix.encode()),
    }}) + record(3, "event_msg", {"event": "child metadata"}))
    empty_parent_prefix = (record(0, "session_meta", {"id": EMPTY_PARENT_THREAD})
                           + record(1, "event_msg", {"event": "no database rows"}))
    (archived / ("rollout-" + EMPTY_PARENT_THREAD + ".jsonl")).write_text(
        empty_parent_prefix)
    (child.parent / ("rollout-" + ONLY_CHILD_THREAD + ".jsonl")).write_text(
        record(2, "session_meta", {"id": ONLY_CHILD_THREAD,
                                   "history_base": {
            "thread_id": EMPTY_PARENT_THREAD, "end_ordinal_exclusive": 2,
            "end_byte_offset": len(empty_parent_prefix.encode()),
        }}) + record(3, "event_msg", {"event": "child metadata"}))


def write_paginated_fixture(database: Path) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE thread_items (thread_id TEXT, turn_id TEXT, "
                           "item_id TEXT, rollout_ordinal INTEGER, created_at_ms INTEGER, "
                           "item_json TEXT, item_type TEXT, updated_at_ordinal INTEGER)")
        connection.execute("CREATE TABLE thread_history_projection_state ("
                           "thread_id TEXT, next_rollout_byte_offset INTEGER, "
                           "next_rollout_ordinal INTEGER)")
        connection.execute("INSERT INTO thread_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (DATABASE_THREAD, "turn-1", "item-1", 1, 100,
                            json.dumps({"id": "item-1", "type": "userMessage",
                                        "content": [{"type": "text", "text": DATABASE_TEXT}]}),
                            "userMessage", 1))
        for thread_id, ordinal, item_id, text in (
                (PARENT_THREAD, 1, "item-parent", INHERITED_TEXT),
                (PARENT_THREAD, 2, "item-parent-later", PARENT_LATER_TEXT),
                (CHILD_THREAD, 3, "item-child", CHILD_TEXT),
                (ONLY_CHILD_THREAD, 3, "item-only-child", ONLY_CHILD_TEXT)):
            connection.execute("INSERT INTO thread_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                               (thread_id, "turn-" + item_id, item_id, ordinal,
                                100 + ordinal,
                                json.dumps({"id": item_id, "type": "userMessage",
                                            "text": text}), "userMessage", ordinal))


def write_state_title_fixture(database: Path) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE threads (id TEXT, title TEXT, name TEXT)")
        connection.execute("INSERT INTO threads VALUES (?, ?, ?)",
                           (DATABASE_THREAD, DATABASE_TITLE, DATABASE_NAME))


def delete_test_key(helper: Path, key_id: str) -> None:
    result = subprocess.run(
        [str(helper), "delete-key", "--key-id", key_id],
        capture_output=True, timeout=15,
    )
    if result.returncode:
        raise AssertionError("Disposable Vault Keychain cleanup failed")


def produce(bundle: Path, helper: Path) -> None:
    if bundle.exists():
        raise AssertionError("The test bundle must start absent")
    source = bundle.parent / "vault-portability-synthetic-source"
    transcript = source / ".codex" / RELATIVE
    transcript.parent.mkdir(parents=True, exist_ok=False)
    transcript.write_bytes(TRANSCRIPT)
    write_fork_rollouts(source / ".codex")
    write_paginated_fixture(source / ".codex/thread_history_1.sqlite")
    write_state_title_fixture(source / ".codex/state_5.sqlite")
    bundle.mkdir(mode=0o700)
    vault = bundle / "vault"
    key_id = None
    try:
        result = backup(str(source), str(vault), crypto_helper=str(helper))
        key_id = result.key_id
        if result.transcript_files != 9 or not result.recovery_key:
            raise AssertionError("Synthetic snapshot was not created")
        receipt = verify_snapshot(str(vault), crypto_helper=str(helper))
        if receipt.snapshot_id != result.snapshot_id:
            raise AssertionError("Producer snapshot verification failed")
        descriptor = os.open(bundle / "recovery-key.txt", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(result.recovery_key + "\n")
        print("Synthetic encrypted snapshot verified on producer Mac")
    finally:
        if key_id:
            delete_test_key(helper, key_id)


def consume(bundle: Path, helper: Path) -> None:
    vault = bundle / "vault"
    key_file = bundle / "recovery-key.txt"
    if not vault.is_dir() or not key_file.is_file():
        raise AssertionError("Synthetic portability artifact is incomplete")
    recovery_key = key_file.read_text(encoding="utf-8").strip()
    if not recovery_key.startswith("CV1-"):
        raise AssertionError("Synthetic recovery key is invalid")
    try:
        verify_snapshot(str(vault), crypto_helper=str(helper))
    except MigrationError:
        pass
    else:
        raise AssertionError("The second Mac unexpectedly already has the producer's Keychain key")
    key_id = None
    try:
        key_id = import_recovery_key(str(vault), recovery_key, crypto_helper=str(helper))
        verified = verify_snapshot(str(vault), crypto_helper=str(helper))
        if verified.transcript_files != 9:
            raise AssertionError("Imported snapshot file count changed")
        empty_home = bundle.parent / "vault-portability-synthetic-empty-home"
        empty_home.mkdir(mode=0o700, exist_ok=False)
        restored_home = bundle.parent / "vault-portability-synthetic-restored"
        restored_home.mkdir(mode=0o700, exist_ok=False)
        restored = restored_home / ".codex"
        result = restore_snapshot(
            str(empty_home), str(vault), str(restored), crypto_helper=str(helper),
        )
        if result.snapshot_id != verified.snapshot_id or (restored / RELATIVE).read_bytes() != TRANSCRIPT:
            raise AssertionError("Cross-Mac synthetic recovery content mismatch")
        if not (restored / "paginated_history" / (DATABASE_THREAD + ".jsonl")).is_file():
            raise AssertionError("Cross-Mac paginated source was not restored")
        catalog = snapshot_catalog(str(vault), crypto_helper=str(helper))
        for title in (DATABASE_TITLE, DATABASE_NAME):
            hits = search_titles(str(vault), title, crypto_helper=str(helper))
            if (len(hits) != 1 or hits[0]["thread_id"] != DATABASE_THREAD):
                raise AssertionError("Cross-Mac state-only title search failed")
        matches = search(str(restored_home), DATABASE_TEXT, catalog=catalog)
        if (len(matches) != 1 or matches[0].collection != "paginated"
                or matches[0].transcript != DATABASE_THREAD + ".jsonl"):
            raise AssertionError("Cross-Mac paginated search did not find the database-only turn")
        page, next_cursor = read_thread_page(
            str(restored_home), "paginated", DATABASE_THREAD + ".jsonl",
            expected_query=DATABASE_TEXT, catalog=catalog,
        )
        if next_cursor is not None or [entry.text for entry in page.entries] != [DATABASE_TEXT]:
            raise AssertionError("Cross-Mac paginated read did not recover the database-only turn")
        exported = b"".join(markdown_chunks(
            str(restored_home), "paginated", DATABASE_THREAD + ".jsonl",
            catalog=catalog))
        if DATABASE_TEXT.encode("utf-8") not in exported:
            raise AssertionError("Cross-Mac paginated Markdown export lost the turn")
        inherited = search(str(restored_home), INHERITED_TEXT, catalog=catalog)
        if {(match.collection, match.transcript) for match in inherited} != {
                ("paginated", PARENT_THREAD + ".jsonl"),
                ("paginated", CHILD_THREAD + ".jsonl")}:
            raise AssertionError("Cross-Mac fork search lost inherited database content")
        later = search(str(restored_home), PARENT_LATER_TEXT, catalog=catalog)
        if {(match.collection, match.transcript) for match in later} != {
                ("paginated", PARENT_THREAD + ".jsonl")}:
            raise AssertionError("Cross-Mac fork search included post-fork parent content")
        child_page, next_cursor = read_thread_page(
            str(restored_home), "paginated", CHILD_THREAD + ".jsonl",
            catalog=catalog)
        if (next_cursor is not None or [entry.text for entry in child_page.entries]
                != [INHERITED_TEXT, CHILD_TEXT]):
            raise AssertionError("Cross-Mac fork read lost inherited database content")
        child_export = b"".join(markdown_chunks(
            str(restored_home), "paginated", CHILD_THREAD + ".jsonl",
            catalog=catalog))
        if (INHERITED_TEXT.encode() not in child_export
                or PARENT_LATER_TEXT.encode() in child_export):
            raise AssertionError("Cross-Mac fork export used the wrong parent bounds")
        if (restored / "paginated_history" / (EMPTY_PARENT_THREAD + ".jsonl")).exists():
            raise AssertionError("Cross-Mac backup invented a zero-row parent projection")
        child_only = search(str(restored_home), ONLY_CHILD_TEXT, catalog=catalog)
        if {(match.collection, match.transcript) for match in child_only} != {
                ("paginated", ONLY_CHILD_THREAD + ".jsonl")}:
            raise AssertionError("Cross-Mac fork search lost a child with a zero-row parent")
        child_only_page, next_cursor = read_thread_page(
            str(restored_home), "paginated", ONLY_CHILD_THREAD + ".jsonl",
            catalog=catalog)
        if (next_cursor is not None or [entry.text for entry in child_only_page.entries]
                != [ONLY_CHILD_TEXT]):
            raise AssertionError("Cross-Mac fork read lost a child with a zero-row parent")
        child_only_export = b"".join(markdown_chunks(
            str(restored_home), "paginated", ONLY_CHILD_THREAD + ".jsonl",
            catalog=catalog))
        if ONLY_CHILD_TEXT.encode() not in child_only_export:
            raise AssertionError("Cross-Mac fork export lost a child with a zero-row parent")
        print("Synthetic snapshot decrypted and restored on independent Mac")
    finally:
        if key_id:
            delete_test_key(helper, key_id)


if __name__ == "__main__":
    if os.environ.get("GITHUB_ACTIONS") != "true" or len(sys.argv) != 4:
        raise SystemExit("Run only on disposable macOS CI: produce|consume BUNDLE HELPER")
    mode, bundle_arg, helper_arg = sys.argv[1:]
    bundle = Path(bundle_arg).resolve()
    helper = Path(helper_arg).resolve()
    if mode == "produce":
        produce(bundle, helper)
    elif mode == "consume":
        consume(bundle, helper)
    else:
        raise SystemExit("Unknown synthetic portability test mode")
