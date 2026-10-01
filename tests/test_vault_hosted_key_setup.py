import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from codex_migrate.errors import MigrationError
from codex_migrate.state import StateStore
from codex_migrate.vault_hosted_key_setup import HostedKeySetup


BINDING = {"deviceId": "11111111-1111-4111-8111-111111111111",
           "accountId": "22222222-2222-4222-8222-222222222222",
           "vaultId": "33333333-3333-4333-8333-333333333333"}
SECRET = "CV1-" + "A" * 43


class HostedKeySetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hosted-key-setup-")
        self.addCleanup(self.temporary.cleanup)
        self.registry = StateStore(self.temporary.name)
        self.registry.sync_recovery_checkpoint = Mock()
        self.native_keys = {}
        self.prepared_ids = []

        def helper(path, args, *, input_data=None):
            key_id = args[2]
            metadata = self.registry.read()["hosted_setup_key"]["metadata"]
            self.assertEqual(key_id, metadata["key_id"])
            self.assertEqual(json.loads((self.registry.root / "hosted-key.json").read_text()), metadata)
            self.assertGreater(self.registry.sync_recovery_checkpoint.call_count, 0)
            if args[0] == "prepare-key":
                self.prepared_ids.append(key_id)
                self.native_keys.setdefault(key_id, SECRET)
                return {"key_id": key_id, "recovery_key": self.native_keys[key_id]}
            self.assertEqual(args[0], "check-recovery-key")
            if input_data != (self.native_keys[key_id] + "\n").encode("ascii"):
                raise MigrationError("wrong synthetic saved copy")
            return {"key_id": key_id, "verified": True}

        self.native = patch("codex_migrate.vault_hosted_key_setup._run_helper", side_effect=helper).start()
        self.addCleanup(patch.stopall)
        patch("codex_migrate.vault_hosted_key_setup._helper_path", return_value=Path("/synthetic/helper")).start()
        self.setup = HostedKeySetup(self.registry)

    def test_checkpoint_precedes_creation_and_no_secret_is_written(self):
        self.assertEqual(self.setup.prepare(BINDING), SECRET)
        self.assertFalse(self.setup.confirmed(BINDING))
        state = self.registry.read()["hosted_setup_key"]
        self.assertEqual(state["binding"], BINDING)
        for item in self.registry.root.iterdir():
            if item.is_file():
                self.assertNotIn(SECRET, item.read_text())
        self.assertEqual((self.registry.root / "hosted-key.json").stat().st_mode & 0o777, 0o600)

    def test_restart_and_prepare_reuse_same_key_and_metadata(self):
        self.setup.prepare(BINDING)
        initial = self.registry.read()["hosted_setup_key"]
        self.setup = HostedKeySetup(self.registry)
        self.assertEqual(self.setup.prepare(BINDING), SECRET)
        self.assertEqual(self.registry.read()["hosted_setup_key"], initial)
        self.assertEqual(len(set(self.prepared_ids)), 1)
        self.assertEqual(len(self.native_keys), 1)

    def test_lost_native_reply_reuses_durable_key_id(self):
        perform = self.native.side_effect
        def lost(*args, **kwargs):
            perform(*args, **kwargs)
            raise MigrationError("response lost")
        self.native.side_effect = lost
        with self.assertRaises(MigrationError):
            self.setup.prepare(BINDING)
        self.native.side_effect = perform
        self.setup = HostedKeySetup(self.registry)
        self.assertEqual(self.setup.prepare(BINDING), SECRET)
        self.assertEqual(len(set(self.prepared_ids)), 1)
        self.assertEqual(len(self.native_keys), 1)

    def test_failed_sync_cannot_touch_keychain_and_restart_resyncs_same_id(self):
        self.registry.sync_recovery_checkpoint.side_effect = OSError("full sync failed")
        with self.assertRaises(OSError):
            self.setup.prepare(BINDING)
        key_id = self.registry.read()["hosted_setup_key"]["metadata"]["key_id"]
        self.native.assert_not_called()
        self.registry.sync_recovery_checkpoint.side_effect = None
        self.setup = HostedKeySetup(self.registry)
        self.setup.prepare(BINDING)
        self.assertEqual(self.prepared_ids, [key_id])

    def test_failed_checkpoint_write_cannot_touch_keychain(self):
        with patch.object(self.registry, "update", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.setup.prepare(BINDING)
        self.native.assert_not_called()
        self.assertNotIn("hosted_setup_key", self.registry.read())

    def test_saved_copy_check_is_stdin_only_and_durable(self):
        self.setup.prepare(BINDING)
        self.setup.confirm(BINDING, SECRET)
        self.assertTrue(HostedKeySetup(self.registry).confirmed(BINDING))
        call = self.native.call_args
        self.assertEqual(call.kwargs["input_data"], (SECRET + "\n").encode("ascii"))
        self.assertNotIn(SECRET, repr(call.args))
        self.assertNotIn(SECRET, self.registry.path.read_text())

    def test_wrong_copy_does_not_import_or_mark_confirmed(self):
        self.setup.prepare(BINDING)
        with self.assertRaises(MigrationError):
            self.setup.confirm(BINDING, "CV1-" + "B" * 43)
        self.assertFalse(self.setup.confirmed(BINDING))
        self.assertEqual(list(self.native_keys.values()), [SECRET])
        self.assertTrue(all(call.args[1][0] in ("prepare-key", "check-recovery-key")
                            for call in self.native.call_args_list))

    def test_backup_metadata_requires_confirmed_copy_and_never_reads_key_material(self):
        with self.assertRaises(MigrationError):
            self.setup.backup_metadata(BINDING)
        self.setup.prepare(BINDING)
        with self.assertRaises(MigrationError):
            self.setup.backup_metadata(BINDING)
        self.setup.confirm(BINDING, SECRET)
        self.native.reset_mock()
        path, key_id = self.setup.backup_metadata(BINDING)
        self.assertEqual(path, self.registry.root / "hosted-key.json")
        self.assertEqual(key_id, self.registry.read()["hosted_setup_key"]["metadata"]["key_id"])
        self.native.assert_not_called()
        path.write_text("{}")
        with self.assertRaises(MigrationError):
            self.setup.backup_metadata(BINDING)
        self.assertEqual(path.read_text(), "{}")

    def test_key_binding_disagreement_never_changes_saved_state(self):
        self.setup.prepare(BINDING)
        before = self.registry.path.read_bytes()
        self.native.reset_mock()
        changed = {**BINDING, "vaultId": BINDING["accountId"]}
        for action in (lambda: self.setup.prepare(changed),
                       lambda: self.setup.confirm(changed, SECRET),
                       lambda: self.setup.confirmed(changed)):
            with self.assertRaises(MigrationError):
                action()
        self.assertEqual(self.registry.path.read_bytes(), before)
        self.native.assert_not_called()

    def test_conflicting_metadata_is_refused_not_replaced(self):
        self.setup.prepare(BINDING)
        path = self.registry.root / "hosted-key.json"
        path.write_text("{}")
        self.native.reset_mock()
        with self.assertRaises(MigrationError):
            self.setup.prepare(BINDING)
        self.assertEqual(path.read_text(), "{}")
        self.native.assert_not_called()

    def test_linked_metadata_is_refused_not_followed(self):
        self.setup.prepare(BINDING)
        path = self.registry.root / "hosted-key.json"
        target = self.registry.root / "target.json"
        target.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(target)
        self.native.reset_mock()
        with self.assertRaises(MigrationError):
            self.setup.prepare(BINDING)
        self.assertTrue(path.is_symlink())
        self.native.assert_not_called()

    def test_bad_native_result_cannot_be_confirmed_as_ready(self):
        for result in ({}, {"key_id": BINDING["deviceId"], "recovery_key": SECRET},
                       {"key_id": BINDING["deviceId"], "recovery_key": "bad"}):
            self.native.return_value = result
            self.native.side_effect = None
            with self.assertRaises(MigrationError):
                self.setup.prepare(BINDING)
            self.assertFalse(self.setup.confirmed(BINDING))

    def test_bad_binding_and_saved_copy_are_rejected_before_native_work(self):
        for binding in ({}, {**BINDING, "token": SECRET}, {**BINDING, "deviceId": "bad"}):
            with self.assertRaises(MigrationError):
                self.setup.prepare(binding)
        for secret in (None, "bad", SECRET + "\n", "CV1-" + "a" * 300):
            with self.assertRaises(MigrationError):
                self.setup.confirm(BINDING, secret)
        self.native.assert_not_called()

    def test_invalid_saved_state_fails_closed(self):
        for value in ({}, [], {"recovery_key": SECRET}):
            self.registry.update(hosted_setup_key=value)
            with self.assertRaises(MigrationError):
                HostedKeySetup(self.registry)
        self.native.assert_not_called()


if __name__ == "__main__":
    unittest.main()
