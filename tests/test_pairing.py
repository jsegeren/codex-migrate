import base64
from dataclasses import replace
import json
import os
import subprocess
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from codex_migrate.config import MigrationConfig
from codex_migrate.errors import MigrationError
from codex_migrate.pairing import Pairing, decode_card, encode_card, public_key
from codex_migrate.transport import SSHTransport


KEY = "ssh-ed25519 " + base64.b64encode(b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + b"x" * 32).decode()


class PairingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        for name in ("old", "new"):
            (self.home / name / "state").mkdir(parents=True, mode=0o700)
        self.old = Pairing(self.home / "old", self.home / "old/state")
        self.new = Pairing(self.home / "new", self.home / "new/state")
        account = patch("codex_migrate.pairing._account", return_value="person")
        account.start()
        self.addCleanup(account.stop)
        self.new._prepare()
        self.details = dict(target="person@fixture.local", home="/Users/person", host_key=KEY)
        receiver = patch.object(self.new, "_receiver_details", return_value=self.details)
        receiver.start()
        self.addCleanup(receiver.stop)

    def pair(self):
        request = self.old.request()["card"]
        accepted = self.new.approve(request, apply=True)["card"]
        self.old.accept(accepted, apply=True)
        return request, accepted

    def test_real_key_exchange_preserves_existing_keys_and_pins_host(self):
        ssh = self.new.home / ".ssh"
        ssh.mkdir(mode=0o700)
        existing = b"# existing access stays unchanged\n"
        (ssh / "authorized_keys").write_bytes(existing)
        (ssh / "authorized_keys").chmod(0o600)
        request, accepted = self.pair()
        content = (ssh / "authorized_keys").read_bytes()
        self.assertTrue(content.startswith(existing))
        self.assertIn(b'restrict,expiry-time="', content)
        self.new.approve(request, apply=True)
        self.assertEqual((ssh / "authorized_keys").read_bytes(), content)
        self.old.accept(accepted, apply=True)
        options = self.old.options("person@fixture.local", "/Users/person")
        self.assertTrue(options.isolated)
        self.assertEqual(Path(options.identity_file).stat().st_mode & 0o777, 0o600)
        self.assertEqual(Path(options.known_hosts_file).stat().st_mode & 0o777, 0o600)
        self.assertNotIn("PRIVATE KEY", request + accepted)
        self.assertEqual(self.old.request()["card"], request)

    def test_no_key_authorization_or_host_trust_without_confirmation(self):
        request = self.old.request()["card"]
        with self.assertRaises(MigrationError):
            self.new.approve(request)
        self.assertFalse((self.new.home / ".ssh").exists())
        accepted = self.new.approve(request, apply=True)["card"]
        with self.assertRaises(MigrationError):
            self.old.accept(accepted)
        self.assertFalse((self.old.root / "known_hosts").exists())

    def test_snapshot_is_read_only_and_restores_each_connection_step(self):
        self.assertEqual(self.old.snapshot(), {})
        self.assertFalse(self.old.root.exists())
        request = self.old.request()["card"]
        reopened = Pairing(self.old.home, self.old.root.parent)
        self.assertEqual(reopened.snapshot()["source"]["card"], request)
        reply = self.new.approve(request, apply=True)["card"]
        path = self.new.home / ".ssh/authorized_keys"
        before = path.stat().st_mtime_ns
        receiver = Pairing(self.new.home, self.new.root.parent)
        self.assertEqual(receiver.snapshot()["receiver"]["card"], reply)
        self.assertEqual(path.stat().st_mtime_ns, before)
        self.old.accept(reply, apply=True)
        source = reopened.snapshot()["source"]
        self.assertEqual(source["status"], "paired")
        self.assertEqual(source["target"], self.details["target"])
        self.assertEqual(source["target_home"], self.details["home"])

    def test_interrupted_approval_can_be_restored_or_revoked_without_authorizing(self):
        from codex_migrate.pairing import _write
        request = self.old.request()["card"]
        def interrupted(path, *args, **kwargs):
            if path.name == "authorized_keys":
                raise OSError("fixture interruption")
            return _write(path, *args, **kwargs)
        with patch("codex_migrate.pairing._write", side_effect=interrupted):
            with self.assertRaises(OSError):
                self.new.approve(request, apply=True)
        path = self.new.home / ".ssh/authorized_keys"
        self.assertFalse(path.exists())
        state = self.new.snapshot()["receiver"]
        self.assertEqual(state["status"], "approval_pending")
        self.assertEqual(state["request_card"], request)
        self.assertFalse(path.exists())
        # Covers interruption before the SSH directory was created as well.
        path.parent.rmdir()
        self.new.revoke(apply=True)
        self.assertFalse(path.parent.exists())
        self.assertFalse((self.new.root / "approved.json").exists())

    def test_edited_or_duplicate_key_never_reports_successful_revocation(self):
        request, _ = self.pair()
        path = self.new.home / ".ssh/authorized_keys"
        owned = path.read_bytes()
        key = decode_card((self.new.root / "approved.json").read_text(), "accepted")["key"].encode()
        for changed in (owned.rstrip(b"\n"), owned.replace(b"restrict,", b""),
                        owned + key + b" additional access\n", key.replace(b" ", b"\t") + b"\n"):
            with self.subTest(kind=changed[:12]):
                path.write_bytes(changed)
                with self.assertRaisesRegex(MigrationError, "unverified"):
                    self.new.snapshot()
                with self.assertRaisesRegex(MigrationError, "unverified"):
                    self.new.revoke(apply=True)
                with self.assertRaisesRegex(MigrationError, "unverified"):
                    self.new.approve(request, apply=True)
                self.assertEqual(path.read_bytes(), changed)
                self.assertTrue((self.new.root / "approved.json").exists())

    def test_expired_snapshot_withholds_cards_and_revocation_survives_clock_changes(self):
        request, _ = self.pair()
        expires = decode_card(request, "request")["expires"]
        with patch("codex_migrate.pairing.time.time", return_value=expires + 1):
            for helper, role in ((self.old, "source"), (self.new, "receiver")):
                state = helper.snapshot()[role]
                self.assertEqual(state["status"], "expired")
                self.assertNotIn("card", state)
                self.assertNotIn("request_card", state)
        with patch("codex_migrate.pairing.time.time", return_value=1):
            self.new.revoke(apply=True)
        self.assertEqual((self.new.home / ".ssh/authorized_keys").read_bytes(), b"")

    def test_snapshot_rejects_changed_trust_and_partial_key_creation(self):
        self.pair()
        path = self.old.root / "known_hosts"
        path.write_bytes(b"different host\n")
        with self.assertRaisesRegex(MigrationError, "changed"):
            self.old.snapshot()
        (self.old.root / "request.json").unlink()
        with self.assertRaisesRegex(MigrationError, "interrupted"):
            self.old.snapshot()

    def test_wrong_reply_and_changed_host_never_replace_trust(self):
        request, accepted = self.pair()
        good = (self.old.root / "known_hosts").read_bytes()
        record = decode_card(accepted, "accepted")
        for field, value in (("id", "0" * 32), ("expires", record["expires"] - 1),
                             ("host_key", KEY.replace("eHh4", "eXl5"))):
            changed = dict(record, **{field: value})
            with self.assertRaises(MigrationError):
                self.old.accept(encode_card(changed), apply=True)
            self.assertEqual((self.old.root / "known_hosts").read_bytes(), good)
        with self.assertRaises(MigrationError):
            self.old.options("other@fixture.local", "/Users/other")

    def test_malformed_expired_injected_and_wrong_step_cards(self):
        request = decode_card(self.old.request()["card"], "request")
        for record in (dict(request, expires=0), dict(request, expires=int(time.time()) + 99999999),
                       dict(request, key=KEY + "\ncommand=evil"), dict(request, surprise=True),
                       dict(request, id="../escape"), dict(request, expires=True)):
            with self.assertRaises(MigrationError):
                decode_card(encode_card(record), "request")
        for card in (None, "junk", "CM-CONNECT-1:!!!!", "x" * 9000):
            with self.assertRaises(MigrationError):
                decode_card(card, "request")
        with self.assertRaises(MigrationError):
            decode_card(encode_card(request), "accepted")
        with self.assertRaises(MigrationError):
            public_key("ssh-ed25519 " + base64.b64encode(b"bad").decode())

    def test_symlink_or_unsafe_ssh_storage_is_not_modified(self):
        request = self.old.request()["card"]
        external = self.home / "external"
        external.mkdir(mode=0o700)
        ssh = self.new.home / ".ssh"
        ssh.symlink_to(external)
        with self.assertRaises(MigrationError):
            self.new.approve(request, apply=True)
        self.assertEqual(list(external.iterdir()), [])
        ssh.unlink()
        ssh.mkdir(mode=0o755)
        ssh.chmod(0o755)
        with self.assertRaises(MigrationError):
            self.new.approve(request, apply=True)
        self.assertEqual(ssh.stat().st_mode & 0o777, 0o755)
        ssh.chmod(0o700)
        other = external / "keys"
        other.write_bytes(b"existing")
        (ssh / "authorized_keys").symlink_to(other)
        with self.assertRaises((OSError, MigrationError)):
            self.new.approve(request, apply=True)
        self.assertEqual(other.read_bytes(), b"existing")

    def test_pairing_options_do_not_use_existing_ssh_config_or_agents(self):
        self.pair()
        options = self.old.options("person@fixture.local", "/Users/person")
        config = MigrationConfig(target="person@fixture.local", target_home="/Users/person", ssh=options)
        args = SSHTransport(config).ssh_base()
        for option in ("StrictHostKeyChecking=yes", "IdentityAgent=none", "IdentitiesOnly=yes",
                       "GlobalKnownHostsFile=/dev/null", "HostKeyAlgorithms=ssh-ed25519"):
            self.assertIn(option, args)
        self.assertEqual(args[args.index("-F") + 1], "/dev/null")
        with self.assertRaises(ValueError):
            replace(options, known_hosts_file=None).validate()

    def test_revoke_preserves_other_entries_and_requires_approval(self):
        request, accepted = self.pair()
        path = self.new.home / ".ssh/authorized_keys"
        paired = path.read_bytes()
        other = b"# existing independent access\n"
        path.write_bytes(other + paired + other)
        with self.assertRaises(MigrationError):
            self.new.revoke()
        self.assertEqual(path.read_bytes(), other + paired + other)
        self.new.revoke(apply=True)
        self.assertEqual(path.read_bytes(), other + other)
        self.assertFalse((self.new.root / "approved.json").exists())
        self.assertEqual(len(list(self.new.root.glob("revoked-*.json"))), 1)

    def test_restart_preserves_old_private_key_and_does_not_revoke_remotely(self):
        self.pair()
        key_info = (self.old.root / "identity").stat()
        authorized = (self.new.home / ".ssh/authorized_keys").read_bytes()
        with self.assertRaises(MigrationError):
            self.old.restart()
        self.old.restart(apply=True)
        retired = list(self.old.root.parent.glob("connection-retired-*"))
        self.assertEqual(len(retired), 1)
        self.assertEqual((retired[0] / "identity").stat().st_ino, key_info.st_ino)
        self.assertEqual((self.new.home / ".ssh/authorized_keys").read_bytes(), authorized)
        fresh = self.old.request()["card"]
        with self.assertRaises(MigrationError):
            self.new.approve(fresh, apply=True)
        self.new.revoke(apply=True)
        self.new.approve(fresh, apply=True)

    def test_generated_key_metadata_is_checked_without_export(self):
        self.old.request()
        path = self.old.root / "identity"
        path.chmod(0o644)
        with self.assertRaises(MigrationError):
            self.old.request()
        path.chmod(0o600)
        os.link(path, self.old.root / "extra-link")
        with self.assertRaises(MigrationError):
            self.old.request()

    def test_existing_public_key_alias_is_not_overwritten(self):
        self.old._prepare()
        other = self.home / "unrelated"
        other.write_bytes(b"untouched")
        (self.old.root / "identity.pub").symlink_to(other)
        with self.assertRaises(MigrationError):
            self.old.request()
        self.assertEqual(other.read_bytes(), b"untouched")

    def test_openssh_accepts_isolated_options_without_contacting_a_host(self):
        self.pair()
        options = self.old.options("person@fixture.local", "/Users/person")
        args = SSHTransport(MigrationConfig(target="person@fixture.local", target_home="/Users/person", ssh=options)).ssh_base()
        result = subprocess.run(args + ["-G", "person@fixture.local"], capture_output=True, text=True, timeout=5, check=True)
        values = dict(line.split(" ", 1) for line in result.stdout.splitlines() if " " in line)
        self.assertEqual(values["stricthostkeychecking"], "true")
        self.assertEqual(values["identityagent"], "none")
        self.assertEqual(values["globalknownhostsfile"], "/dev/null")
        self.assertEqual(values["userknownhostsfile"], options.known_hosts_file)
        self.assertEqual(values["hostkeyalias"], options.host_key_alias)


if __name__ == "__main__":
    unittest.main()
