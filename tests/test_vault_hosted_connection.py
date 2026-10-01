import json
from pathlib import Path
import tempfile
import unittest

from codex_migrate.errors import MigrationError
from codex_migrate.vault_hosted_connection import (
    active_binding, connection_path, save_connection,
)
from codex_migrate.vault_schedule import _update_lock


BINDING = {"deviceId": "11111111-1111-4111-8111-111111111111",
           "accountId": "22222222-2222-4222-8222-222222222222",
           "vaultId": "33333333-3333-4333-8333-333333333333",
           "keyId": "44444444-4444-4444-8444-444444444444"}
NEW = "55555555-5555-4555-8555-555555555555"


class HostedConnectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = str(Path(temporary.name).resolve())

    def test_missing_reference_uses_original_without_creating_state(self):
        self.assertEqual(active_binding(self.home, BINDING), BINDING)
        self.assertFalse(connection_path(self.home).parent.exists())

    def test_rotation_is_private_idempotent_and_never_changes_key(self):
        with _update_lock(self.home):
            save_connection(self.home, BINDING)
            updated = {**BINDING, "deviceId": NEW}
            save_connection(self.home, updated, previous_device=BINDING["deviceId"])
            save_connection(self.home, updated, previous_device=BINDING["deviceId"])
            self.assertEqual(active_binding(self.home, BINDING), updated)
        path = connection_path(self.home)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(set(json.loads(path.read_text())),
                         {"format", "version", "owner_kind", "binding"})

    def test_unexplained_device_and_changed_owner_or_key_never_replace_reference(self):
        save_connection(self.home, BINDING)
        path = connection_path(self.home)
        before = path.read_bytes()
        for binding, kwargs in (({**BINDING, "deviceId": NEW}, {}),
                ({**BINDING, "keyId": NEW}, {"previous_device": BINDING["deviceId"]}),
                ({**BINDING, "accountId": NEW}, {}),
                ({**BINDING, "vaultId": NEW}, {}), (BINDING, {"owner_kind": "business"})):
            with self.subTest(binding=binding, kwargs=kwargs):
                with self.assertRaises(MigrationError):
                    save_connection(self.home, binding, **kwargs)
                self.assertEqual(path.read_bytes(), before)
        for field in ("accountId", "vaultId", "keyId"):
            with self.assertRaises(MigrationError):
                active_binding(self.home, {**BINDING, field: NEW})

    def test_pending_rotation_refuses_stale_device_use(self):
        save_connection(self.home, BINDING)
        pending = connection_path(self.home).with_name("hosted-rotation.json")
        pending.write_text("{}")
        pending.chmod(0o600)
        with self.assertRaisesRegex(MigrationError, "pending hosted device"):
            active_binding(self.home, BINDING)

    def test_malformed_and_nonprivate_references_fail_closed(self):
        save_connection(self.home, BINDING)
        path = connection_path(self.home)
        valid = json.loads(path.read_text())
        for value in ({}, {**valid, "version": True}, {**valid, "secret": "not allowed"},
                      {**valid, "binding": {**BINDING, "keyId": "bad"}}):
            path.write_text(json.dumps(value))
            with self.assertRaises(MigrationError):
                active_binding(self.home, BINDING)
            with self.assertRaises(MigrationError):
                save_connection(self.home, BINDING)
        path.write_text(json.dumps(valid))
        path.chmod(0o644)
        with self.assertRaises(MigrationError):
            active_binding(self.home, BINDING)

    def test_linked_and_dangling_references_are_not_replaced(self):
        save_connection(self.home, BINDING)
        path = connection_path(self.home)
        target = path.with_name("target.json")
        path.rename(target)
        path.symlink_to(target)
        for exists in (True, False):
            if not exists:
                target.unlink()
            with self.assertRaises(MigrationError):
                active_binding(self.home, BINDING)
            with self.assertRaises(MigrationError):
                save_connection(self.home, BINDING)
            self.assertTrue(path.is_symlink())
