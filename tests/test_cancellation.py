import contextlib
import io
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import unittest
from unittest.mock import patch

from codex_migrate.cancellation import Cancellation
from codex_migrate.cli import main
from codex_migrate.config import MigrationConfig
from codex_migrate.transport import SSHTransport, TransferProcess, _stop_process


class CancellationTests(unittest.TestCase):
    def test_dashboard_interrupt_does_not_claim_pre_replacement(self):
        error = io.StringIO()
        with patch("codex_migrate.cli.StateStore"), \
             patch("codex_migrate.cli.MigrationEngine"), \
             patch("codex_migrate.cli.Dashboard") as dashboard, \
             contextlib.redirect_stderr(error):
            dashboard.return_value.serve.side_effect = KeyboardInterrupt
            result = main(["serve", "--target", "user@fixture.local",
                           "--target-home", "/Users/user"])
        self.assertEqual(result, 130)
        self.assertNotIn("before replacement", error.getvalue())
        self.assertIn("Review migration status and backup receipts", error.getvalue())

    def test_stop_after_install_does_not_report_before_replacement(self):
        def completed(config, components, cancellation):
            class Export:
                def run(self):
                    with cancellation.replacement():
                        return {"applied": True, "item_count": 0, "components": [],
                                "items": [], "backup": "/Users/user/fixture-backup"}
            return Export()
        output, error = io.StringIO(), io.StringIO()
        with patch("codex_migrate.cli.ComponentExporter", side_effect=completed), \
             patch("codex_migrate.cli.StateStore") as state, \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            state.return_value.release_process_lock.side_effect = lambda: signal.raise_signal(signal.SIGINT)
            result = main(["export", "--apply", "--target", "user@fixture.local",
                           "--target-home", "/Users/user"])
        self.assertEqual(result, 0)
        self.assertIn("Exported", output.getvalue())
        self.assertNotIn("stopped before replacement", error.getvalue())

    def test_cleanup_reaps_descendants_after_leader_exits(self):
        script = "import subprocess,sys; subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])"
        process = subprocess.Popen([sys.executable, "-c", script],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=True)
        try:
            process.wait(timeout=5)
            _stop_process(process)
            # Inherited pipes must reach EOF; leader exit alone is insufficient.
            process.communicate(timeout=1)
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate(timeout=5)

    def test_stop_interrupts_planning_and_restores_handlers(self):
        previous = signal.getsignal(signal.SIGTERM)
        with self.assertRaises(KeyboardInterrupt):
            with Cancellation().signals():
                signal.raise_signal(signal.SIGTERM)
        self.assertEqual(signal.getsignal(signal.SIGTERM), previous)

    def test_replacement_defers_stop_through_receipt(self):
        output = io.StringIO()
        with contextlib.redirect_stderr(output), Cancellation().signals() as cancellation:
            with cancellation.replacement():
                signal.raise_signal(signal.SIGINT)
            signal.raise_signal(signal.SIGTERM)
        self.assertIn("Finishing backup", output.getvalue())

    def test_repeated_signal_does_not_interrupt_cleanup(self):
        with Cancellation().signals():
            try:
                signal.raise_signal(signal.SIGINT)
            except KeyboardInterrupt:
                signal.raise_signal(signal.SIGTERM)

    def test_transfer_interrupt_reaps_real_child(self):
        transfer = TransferProcess([sys.executable, "-u", "-c",
                                    "import time; print('ready'); time.sleep(60)"])
        def interrupt(_):
            raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            transfer.start(interrupt)
        self.assertIsNotNone(transfer.process.poll())
        self.assertTrue(transfer.process.stdout.closed)

    def test_remote_interrupt_reaps_real_child(self):
        transport = SSHTransport(MigrationConfig(target="user@fixture.local",
                                                target_home="/Users/user"))
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, start_new_session=True)
        original = process.communicate
        calls = []
        def interrupted(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise KeyboardInterrupt
            return original(*args, **kwargs)
        try:
            with patch("codex_migrate.transport.subprocess.Popen", return_value=process), \
                 patch.object(process, "communicate", side_effect=interrupted):
                with self.assertRaises(KeyboardInterrupt):
                    transport.run_remote("read-only fixture")
            self.assertIsNotNone(process.poll())
            self.assertEqual(transport._active_remote, [])
        finally:
            if process.poll() is None:
                process.kill()
            original()

    def test_sigterm_stops_running_transfer_without_orphan(self):
        root = Path(__file__).resolve().parents[1]
        script = """
import sys
from codex_migrate.cancellation import Cancellation
from codex_migrate.transport import TransferProcess
p = TransferProcess([sys.executable, '-u', '-c', 'import os,time; print(os.getpid()); time.sleep(60)'])
try:
    with Cancellation().signals():
        p.start(lambda line: print(line, flush=True))
except KeyboardInterrupt:
    sys.exit(130)
"""
        process = subprocess.Popen([sys.executable, "-u", "-c", script],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   env=dict(os.environ, PYTHONPATH=str(root / "src")))
        try:
            self.assertTrue(select.select([process.stdout], [], [], 10)[0])
            child_pid = int(process.stdout.readline())
            process.terminate()
            self.assertEqual(process.wait(timeout=10), 130)
            with self.assertRaises(ProcessLookupError):
                os.kill(child_pid, 0)
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)
