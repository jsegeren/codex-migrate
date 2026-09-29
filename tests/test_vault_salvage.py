import json
import io
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from codex_migrate.errors import MigrationError
from codex_migrate.vault import search
from codex_migrate import vault_salvage
from codex_migrate.cli import main


def record(text):
    return (json.dumps({"payload": {"message": {"content": text}}}) + "\n").encode()


class VaultSalvageTests(unittest.TestCase):
    def fixture(self, root):
        path = root / ".codex/sessions/damaged.jsonl"
        path.parent.mkdir(parents=True)
        return path

    def test_recovers_bounded_records_around_nuls_without_changing_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            path = self.fixture(home)
            original = (record("Before damage") + b"\x00\x00" + record("After NUL") +
                        b"not-json\n" + record("After malformed record"))
            path.write_bytes(original)
            (home / ".codex/auth.json").write_text("NEVER-READ-AUTH", encoding="utf-8")
            with self.assertRaisesRegex(MigrationError, "unreadable JSON"):
                search(str(home), "After malformed")
            result = vault_salvage.preview_damaged_thread(
                str(home), "active", "damaged.jsonl")
            self.assertEqual([entry.text for entry in result.entries],
                             ["Before damage", "After NUL", "After malformed record"])
            self.assertEqual((result.parsed_records, result.nul_repaired_records,
                              result.skipped_records, result.preview_truncated),
                             (3, 1, 1, False))
            self.assertIn("not the original", vault_salvage.incomplete_markdown(result))
            self.assertIn("Skipped records: 1", vault_salvage.incomplete_markdown(result))
            self.assertTrue(result.physical_file_only)
            self.assertEqual(result.as_dict()["skipped_records"], 1)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual((home / ".codex/auth.json").read_text(), "NEVER-READ-AUTH")

    def test_invalid_utf8_oversized_and_nonobject_records_are_counted_not_invented(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            path = self.fixture(home)
            path.write_bytes(b"\xff\n" + b"x" * (vault_salvage.MAX_SALVAGE_RECORD_BYTES + 8) +
                             b"\n" + b"[]\n" + record("Survives"))
            result = vault_salvage.preview_damaged_thread(
                str(home), "active", "damaged.jsonl")
            self.assertEqual([entry.text for entry in result.entries], ["Survives"])
            self.assertEqual(result.skipped_records, 3)
            self.assertEqual(result.parsed_records, 1)

    def test_nul_insertion_is_parseable_but_overwritten_structure_is_not_invented(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            path = self.fixture(home)
            inserted = record("Known text").replace(b"Known", b"Kn\x00own")
            overwritten = record("Unrecoverable").replace(
                b'{"payload":', b'\x00"payload":')
            original = inserted + overwritten + record("Later intact")
            path.write_bytes(original)
            result = vault_salvage.preview_damaged_thread(
                str(home), "active", "damaged.jsonl")
            self.assertEqual([entry.text for entry in result.entries],
                             ["Known text", "Later intact"])
            self.assertEqual((result.parsed_records, result.nul_repaired_records,
                              result.skipped_records), (2, 1, 1))
            self.assertIn("Records parsed after NUL removal: 1",
                          vault_salvage.incomplete_markdown(result))
            self.assertEqual(path.read_bytes(), original)

    def test_preview_limit_is_explicit_and_does_not_stop_damage_counting(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            path = self.fixture(home)
            path.write_bytes(record("First") + record("Second") + b"bad\n")
            result = vault_salvage.preview_damaged_thread(
                str(home), "active", "damaged.jsonl", max_entries=1)
            self.assertEqual([entry.text for entry in result.entries], ["First"])
            self.assertTrue(result.preview_truncated)
            self.assertEqual((result.parsed_records, result.skipped_records), (2, 1))

    def test_linked_or_changed_source_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            path = self.fixture(home)
            outside = home / "outside.jsonl"
            outside.write_bytes(record("Outside"))
            path.symlink_to(outside)
            with self.assertRaises(MigrationError):
                vault_salvage.preview_damaged_thread(str(home), "active", "damaged.jsonl")
            path.unlink()
            path.write_bytes(record("Before"))
            original_strings = vault_salvage._strings

            def mutate(record_value):
                path.write_bytes(record("Changed"))
                return original_strings(record_value)

            with patch.object(vault_salvage, "_strings", side_effect=mutate):
                with self.assertRaisesRegex(MigrationError, "changed during salvage"):
                    vault_salvage.preview_damaged_thread(
                        str(home), "active", "damaged.jsonl")

    def test_cli_requires_exact_collection_and_labels_incomplete_preview(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            path = self.fixture(home)
            path.write_bytes(record("Recovered text") + b"bad\n")
            output = io.StringIO()
            with redirect_stdout(output):
                status = main(["vault", "--source-home", str(home),
                               "salvage-preview", "active", "damaged.jsonl"])
            self.assertEqual(status, 0)
            self.assertIn("INCOMPLETE READ-ONLY PREVIEW", output.getvalue())
            self.assertIn("skipped: 1", output.getvalue())
            self.assertIn("Recovered text", output.getvalue())
            self.assertEqual(path.read_bytes(), record("Recovered text") + b"bad\n")

    def test_scan_budget_is_explicit(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            path = self.fixture(home)
            path.write_bytes(record("First") + record("Second"))
            with patch.object(vault_salvage, "MAX_SCAN_BYTES", len(record("First"))):
                result = vault_salvage.preview_damaged_thread(
                    str(home), "active", "damaged.jsonl")
            self.assertEqual([entry.text for entry in result.entries], ["First"])
            self.assertTrue(result.scan_truncated)

    def test_scan_budget_never_parses_a_record_past_the_limit(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            path = self.fixture(home)
            original = record("Long surviving record") + record("Past the limit")
            path.write_bytes(original)
            with patch.object(vault_salvage, "MAX_SCAN_BYTES", 20):
                result = vault_salvage.preview_damaged_thread(
                    str(home), "active", "damaged.jsonl")
            self.assertEqual(result.entries, [])
            self.assertEqual(result.parsed_records, 0)
            self.assertTrue(result.scan_truncated)
            self.assertEqual(path.read_bytes(), original)

    def test_oversized_drain_respects_the_scan_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            path = self.fixture(home)
            original = b"x" * 100 + b"\n" + record("After oversized record")
            path.write_bytes(original)
            with patch.object(vault_salvage, "MAX_SCAN_BYTES", 50), patch.object(
                    vault_salvage, "MAX_SALVAGE_RECORD_BYTES", 8):
                result = vault_salvage.preview_damaged_thread(
                    str(home), "active", "damaged.jsonl")
            self.assertEqual(result.entries, [])
            self.assertEqual(result.skipped_records, 1)
            self.assertTrue(result.scan_truncated)
            self.assertEqual(path.read_bytes(), original)

    def test_discovery_finds_old_title_without_parsing_damaged_body(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            thread_id = "11111111-1111-4111-8111-111111111111"
            path = home / ".codex/sessions/rollout-{}.jsonl".format(thread_id)
            path.parent.mkdir(parents=True)
            path.write_bytes(b"damaged JSONL\n")
            (home / ".codex/session_index.jsonl").write_text(
                json.dumps({"id": thread_id, "thread_name": "Old title"}) + "\n"
                + json.dumps({"id": thread_id, "thread_name": "New title"}) + "\n")
            result = vault_salvage.find_transcripts(str(home), "Old title")
            self.assertEqual(result["results"][0]["title"], "New title")
            self.assertEqual(result["results"][0]["transcript"], path.name)
            self.assertTrue(result["titles_available"])
            (home / ".codex/session_index.jsonl").write_bytes(b"invalid\n")
            fallback = vault_salvage.find_transcripts(str(home), "rollout-")
            self.assertFalse(fallback["titles_available"])
            self.assertEqual(fallback["results"][0]["transcript"], path.name)
