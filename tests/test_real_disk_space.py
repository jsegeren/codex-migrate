"""Opt-in, bounded APFS image acceptance; never fills a real home volume.

Run on macOS with CODEX_MIGRATE_REAL_DISK_TEST=yes and PYTHONPATH=src:tests:
python3 -m unittest test_real_disk_space -v

Uses the existing local installer fixture (synthetic identity and process
snapshot), not SSH, actual Codex state, or a complete packaged buyer flow.
"""

from dataclasses import replace
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import tempfile
import unittest

import test_backup as fixtures
from codex_migrate.backup import MIN_RESERVE_BYTES
from codex_migrate.migration import MigrationEngine
from codex_migrate.transaction import TRANSACTION_NAME


@unittest.skipUnless(platform.system() == "Darwin" and
                     os.environ.get("CODEX_MIGRATE_REAL_DISK_TEST") == "yes",
                     "opt-in macOS disk-image acceptance")
class RealDiskSpaceTests(unittest.TestCase):
    def setUp(self):
        self.disk_root = Path(tempfile.mkdtemp(prefix="codex-migrate-disk-test-")).resolve()
        self.mount = self.disk_root / "mounted"
        self.mount.mkdir()
        self.addCleanup(self.cleanup_disk)
        if shutil.disk_usage(self.disk_root).free < 8 * 1024**3:
            self.skipTest("Disk-image acceptance requires 8 GiB of host free space")
        self.image = self.disk_root / "fixture.sparseimage"
        self.run_tool(["/usr/bin/hdiutil", "create", "-size", "3072m", "-fs", "APFS",
                       "-type", "SPARSE", "-volname", "CodexMigrateDiskFixture",
                       "-nospotlight", str(self.image)])
        self.run_tool(["/usr/bin/hdiutil", "attach", "-nobrowse", "-owners", "on",
                       "-mountpoint", str(self.mount), str(self.image)])
        self.assertTrue(os.path.ismount(self.mount))
        self.assertNotEqual(self.mount.stat().st_dev, self.disk_root.stat().st_dev)
        self.assertLess(shutil.disk_usage(self.mount).total, 4 * 1024**3)
        self.assertGreater(shutil.disk_usage(self.mount).free, MIN_RESERVE_BYTES)
        self.fixture = fixtures.BackupTests()
        self.fixture.setUp()
        # Source/state are outside the mounted image, so failed detach cannot
        # make TemporaryDirectory cleanup traverse a still-mounted filesystem.
        self.addCleanup(self.fixture.tearDown)
        shutil.move(str(self.fixture.target), str(self.mount / "target"))
        self.fixture.target = self.mount / "target"
        self.fixture.config = replace(self.fixture.config,
                                      target_home=str(self.fixture.target)).validate()
        self.fixture.stage = Path(self.fixture.config.target_staging)
        self.fixture.engine = MigrationEngine(self.fixture.config, self.fixture.state)
        self.engine = self.fixture.engine
        self.engine.transport = self.fixture.transport()
        self.filler = self.mount / "disposable-space-pressure"

    def run_tool(self, command):
        result = subprocess.run(command, capture_output=True, text=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def cleanup_disk(self):
        if os.path.ismount(self.mount):
            result = subprocess.run(["/usr/bin/hdiutil", "detach", str(self.mount)],
                                    capture_output=True, text=True, timeout=60)
            if result.returncode or os.path.ismount(self.mount):
                raise RuntimeError("Detach failed; retained disk fixture at " + str(self.disk_root))
        # Never recursively clean through a mount, or force-detach anything.
        if self.mount.exists() and self.mount.stat().st_dev != self.disk_root.stat().st_dev:
            raise RuntimeError("Unexpected mounted fixture retained at " + str(self.disk_root))
        shutil.rmtree(self.disk_root)

    def assert_contained_failure(self):
        self.fixture.assert_originals_untouched()
        self.assertFalse((self.fixture.target / TRANSACTION_NAME).exists())
        self.assertFalse((Path(self.fixture.state.read()["pending_backup"]) /
                          "verification.json").exists())
        self.assertEqual((self.fixture.source / "Git/new.txt").read_text(), "new-work")

    def retry_after_reclaim(self):
        # Remove only the exact artificial pressure file, never source, staging
        # or the failed attempt's backup. A new install attempt retains that backup.
        self.filler.unlink()
        self.assertGreater(shutil.disk_usage(self.mount).free, MIN_RESERVE_BYTES)
        self.engine.transport = self.fixture.transport()
        receipt = self.engine._install_and_verify()
        self.assertTrue(receipt["backup_verified"])
        self.assertEqual((self.fixture.target / "Git/new.txt").read_text(), "new-work")
        self.assertEqual((Path(receipt["backup"]) / "home-relative/Git/old.txt").read_text(),
                         "original-work")
        self.assertFalse((self.fixture.target / TRANSACTION_NAME).exists())

    def test_real_low_free_space_blocks_then_allows_retry(self):
        self.run_tool(["/bin/dd", "if=/dev/zero", "of=" + str(self.filler),
                       "bs=1048576", "count=1280"])
        self.assertLess(shutil.disk_usage(self.mount).free, MIN_RESERVE_BYTES)
        with self.assertRaisesRegex(RuntimeError, "Not enough destination space"):
            self.engine._install_and_verify()
        self.assert_contained_failure()
        self.assertFalse(Path(self.fixture.state.read()["pending_backup"]).exists())
        self.retry_after_reclaim()

    def pressure_after_backup(self, megabytes):
        marker = "verify_backup " + shlex.quote(str(self.fixture.target / ".codex"))
        original = self.engine.transport.run_remote
        def with_pressure(script, timeout=60):
            self.assertEqual(script.count(marker), 1)
            end = script.index("\n", script.index(marker))
            pressure = ("\nLC_ALL=C /bin/dd if=/dev/zero of=" + shlex.quote(str(self.filler)) +
                        " bs=1048576 count=" + str(megabytes) + "\n")
            return original(script[:end] + pressure + script[end:], timeout=180)
        self.engine.transport.run_remote = with_pressure

    def test_real_space_consumed_during_backup_blocks_replacement(self):
        # The allocation succeeds; the production second df check must reject
        # the genuinely reduced free space, not an injected df result or error.
        self.pressure_after_backup(1280)
        with self.assertRaisesRegex(RuntimeError, "Not enough destination space"):
            self.engine._install_and_verify()
        self.assertLess(shutil.disk_usage(self.mount).free, MIN_RESERVE_BYTES)
        self.assert_contained_failure()
        self.assertTrue(Path(self.fixture.state.read()["pending_backup"]).exists())
        self.retry_after_reclaim()

    def test_real_enospc_after_backup_preserves_data_then_allows_retry(self):
        # Deliberately consume this <4-GiB image after cloning the Codex backup.
        # Real df/du/cp and installer checks remain intact. dd must fail because
        # its bounded 4-GiB request exceeds the independently verified image size.
        # This tests a real filesystem write error in the installer shell, not
        # ENOSPC during a production copy, journal write, or protected rollback.
        self.pressure_after_backup(4096)
        with self.assertRaisesRegex(RuntimeError, "No space left on device"):
            self.engine._install_and_verify()
        self.assert_contained_failure()
        failed_backup = Path(self.fixture.state.read()["pending_backup"])
        self.assertEqual((failed_backup / ".codex/old.txt").read_text(), "original")
        self.retry_after_reclaim()
        self.assertTrue(failed_backup.exists())


if __name__ == "__main__":
    unittest.main()
