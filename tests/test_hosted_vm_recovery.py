"""Guard tests; fake VM states do not certify actual cloud recovery."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "ops"))
try:
    import hosted_vm_recovery as VM
finally:
    sys.path.pop(0)


class OwnedVMTests(unittest.TestCase):
    def inputs(self):
        return {"root": VM.ROOT + "/receiver", "crypto_helper": VM.ROOT + "/helper",
            "publication_receipt": VM.ROOT + "/publication.json",
            "recovery_key_file": VM.ROOT + "/saved-key",
            "device_id": "11111111-1111-4111-8111-111111111111",
            "account_id": "22222222-2222-4222-8222-222222222222",
            "vault_id": "33333333-3333-4333-8333-333333333333"}

    def test_fixed_vm_command_and_stop_before_success(self):
        order = []
        with patch.object(VM, "running", return_value=True), \
                patch.object(VM, "relay_process", side_effect=lambda *a, **kw: order.append((a, kw)) or {"passed": True}), \
                patch.object(VM, "stop_and_verify", side_effect=lambda: order.append("stopped")):
            result = VM.recover_in_vm("preview", "workspace", self.inputs())
        command = order[0][0][0]
        self.assertEqual(order[0][1], {"environment": VM.ENV})
        self.assertEqual(command[:4], [VM.TART, "exec", "-i", VM.VM])
        self.assertIn("--stdio-preview-recovery", command)
        self.assertIn("--apply", command)
        self.assertNotIn("-c", command)
        self.assertEqual(order[-1], "stopped")
        self.assertEqual(result, {"passed": True, "owned_vm_stopped_verified": True})

    def test_failure_and_keyboard_interrupt_still_stop_vm(self):
        for error in (ValueError("private provider diagnostic"), KeyboardInterrupt()):
            with patch.object(VM, "running", return_value=True), \
                    patch.object(VM, "relay_process", side_effect=error), \
                    patch.object(VM, "stop_and_verify") as stop:
                with self.assertRaises(KeyboardInterrupt if isinstance(error, KeyboardInterrupt) else ValueError) as caught:
                    VM.recover_in_vm("preview", "workspace", self.inputs())
                self.assertNotIn("private", str(caught.exception))
                stop.assert_called_once()

    def test_unverified_shutdown_cannot_return_success(self):
        with patch.object(VM, "running", return_value=True), \
                patch.object(VM, "relay_process", return_value={"passed": True}), \
                patch.object(VM, "stop_and_verify", side_effect=RuntimeError("secret")):
            with self.assertRaisesRegex(ValueError, "^owned_vm_shutdown_not_verified$"):
                VM.recover_in_vm("preview", "workspace", self.inputs())

    def test_stopped_vm_does_not_launch_or_implicitly_start(self):
        with patch.object(VM, "running", return_value=False), patch.object(VM, "relay_process") as relay:
            with self.assertRaises(ValueError):
                VM.recover_in_vm("preview", "workspace", self.inputs())
            relay.assert_not_called()

    def test_secret_arguments_and_outside_paths_refused_before_vm_control(self):
        for changes in ({"token": "private"}, {"root": "/Users/admin/.codex"},
                        {"recovery_key_file": "cvk1-secret-key-value"},
                        {"crypto_helper": VM.ROOT + "/../other"}, {"device_id": "credential"}):
            with patch.object(VM, "running") as state, patch.object(VM, "relay_process") as relay:
                with self.assertRaises((ValueError, AttributeError)):
                    VM.recover_in_vm("preview", "workspace", {**self.inputs(), **changes})
                state.assert_not_called()
                relay.assert_not_called()

    def test_live_state_exact_target_and_consistency(self):
        good = {"Name": VM.VM, "Source": "local", "State": "running", "Running": True}
        for entries, valid in (([good], True), ([{**good, "Name": "other-vm"}], False),
                               ([good, good], False), ([{**good, "Running": 1}], False),
                               ([{**good, "State": "stopped"}], False)):
            result = subprocess.CompletedProcess([], 0, json.dumps(entries).encode(), b"")
            with patch.object(VM, "tart", return_value=result):
                if valid:
                    self.assertTrue(VM.running())
                else:
                    with self.assertRaises(ValueError):
                        VM.running()

    def test_stop_is_fixed_and_state_rechecked(self):
        with patch.object(VM, "running", return_value=False), \
                patch.object(VM, "tart", return_value=subprocess.CompletedProcess([], 0)) as tart:
            VM.stop_and_verify()
            tart.assert_called_once_with(["stop", VM.VM])
        with patch.object(VM, "running", return_value=True), \
                patch.object(VM, "tart", return_value=subprocess.CompletedProcess([], 0)):
            with self.assertRaises(ValueError):
                VM.stop_and_verify()

    def test_metadata_failure_cannot_prevent_fixed_stop_attempt(self):
        with patch.object(VM, "running", side_effect=ValueError("metadata unavailable")), \
                patch.object(VM, "tart", return_value=subprocess.CompletedProcess([], 0)) as tart:
            with self.assertRaises(ValueError):
                VM.stop_and_verify()
            tart.assert_called_once_with(["stop", VM.VM])

    def test_lost_stop_reply_requires_final_live_stopped_state(self):
        for state in (True, False):
            with patch.object(VM, "running", return_value=state), \
                    patch.object(VM, "tart", side_effect=subprocess.TimeoutExpired([VM.TART], 30)) as tart:
                if state:
                    with self.assertRaises(ValueError):
                        VM.stop_and_verify()
                else:
                    VM.stop_and_verify()
                tart.assert_called_once_with(["stop", VM.VM])


if __name__ == "__main__":
    unittest.main()
