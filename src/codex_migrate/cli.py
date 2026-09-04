"""Command-line interface for Codex Migrate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import List, Optional

from codex_migrate import __version__
from codex_migrate.cancellation import Cancellation
from codex_migrate.components import ComponentExporter, SUPPORTED_COMPONENTS
from codex_migrate.config import MigrationConfig, SSHOptions
from codex_migrate.dashboard import Dashboard
from codex_migrate.inventory import collect
from codex_migrate.migration import MigrationEngine
from codex_migrate.security import redact
from codex_migrate.state import StateStore


def _port(value: str) -> int:
    port = int(value)
    if port < 0 or port > 65535:
        raise argparse.ArgumentTypeError("port must be between 0 and 65535 (0 selects a free port)")
    return port


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="codex-migrate",
        description="Unofficial, resumable Mac-to-Mac migration for local Codex workspaces.",
    )
    root.add_argument("--version", action="version", version=__version__)
    commands = root.add_subparsers(dest="command", required=True)

    launch = commands.add_parser("launch", help="Open guided setup in your browser")
    launch.add_argument("--source-home", default=str(Path.home()))
    launch.add_argument("--state-dir", default=str(Path.home() / ".local/state/codex-migrate-browser"))
    launch.add_argument("--port", type=_port, default=0)
    launch.add_argument("--no-open", action="store_true")

    inventory = commands.add_parser("inventory", help="Inspect local data without changing it")
    inventory.add_argument("--source-home", default=str(Path.home()))
    inventory.add_argument("--workspace", action="append", default=[])
    inventory.add_argument("--json", action="store_true")

    serve = commands.add_parser("serve", help="Start the local progress dashboard")
    _migration_arguments(serve)
    serve.add_argument("--port", type=_port, default=8765)
    serve.add_argument("--no-open", action="store_true")

    inspect = commands.add_parser("inspect", help="Run source and destination preflight")
    _migration_arguments(inspect)
    inspect.add_argument("--json", action="store_true")

    export = commands.add_parser(
        "export",
        help="Export selected repair components without repeating the full migration",
    )
    _migration_arguments(export)
    export.add_argument(
        "--component",
        action="append",
        choices=SUPPORTED_COMPONENTS,
        default=[],
        help="Component to export; repeat to select more than one",
    )
    export.add_argument("--json", action="store_true")

    recovery = commands.add_parser("recovery", help="Inspect an interrupted destination installation without changing files")
    _migration_arguments(recovery)
    recovery.add_argument("--json", action="store_true")

    return root


def _migration_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--target", required=True, help="SSH destination, such as user@new-mac.local")
    command.add_argument("--target-home", required=True, help="Absolute destination home directory")
    command.add_argument("--source-home", default=str(Path.home()))
    command.add_argument("--workspace", action="append", default=[])
    command.add_argument("--state-dir", default=str(Path.home() / ".local/state/codex-migrate"))
    command.add_argument("--identity-file")
    command.add_argument("--known-hosts-file")
    command.add_argument("--host-key-alias")
    command.add_argument("--no-compress", action="store_true")
    command.add_argument(
        "--apply",
        action="store_true",
        help="Enable transfer and installation controls; otherwise the dashboard is read-only",
    )


def _config(args: argparse.Namespace) -> MigrationConfig:
    return MigrationConfig(
        target=args.target,
        target_home=args.target_home,
        source_home=args.source_home,
        workspace_roots=args.workspace,
        state_dir=args.state_dir,
        apply=args.apply,
        compress=not args.no_compress,
        ssh=SSHOptions(
            identity_file=args.identity_file,
            known_hosts_file=args.known_hosts_file,
            host_key_alias=args.host_key_alias,
        ),
    ).validate()


def main(argv: Optional[List[str]] = None) -> int:
    internal = argv if argv is not None else sys.argv[1:]
    if internal[:1] == ["_ssh-rsync"]:
        from codex_migrate.ssh_bridge import run
        try:
            run(internal[1:])
        except Exception:
            print("Codex Migrate could not safely start the rsync SSH connection. Review the destination and contact support.", file=sys.stderr)
            return 76
        return 76  # exec is not expected to return; never fall through to commands.
    args = parser().parse_args(argv)
    try:
        if args.command == "launch":
            from codex_migrate.setup import SetupDashboard
            SetupDashboard(args.source_home, args.state_dir, args.port).serve(open_browser=not args.no_open)
            return 0
        if args.command == "inventory":
            result = collect(args.source_home, args.workspace)
            if args.json:
                print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
            else:
                print("Active conversations: %d" % result.active_sessions.files)
                print("Archived conversations: %d" % result.archived_sessions.files)
                print("Git repositories: %d" % result.git_repositories)
                print("Personal custom skills: %d" % len(result.personal_skills))
                print("Estimated bytes: %d" % result.estimated_transfer_bytes)
                if result.unreadable_paths:
                    print("Unreadable paths: %d" % len(result.unreadable_paths))
            return 0

        config = _config(args)
        if args.command == "recovery":
            from codex_migrate.recovery import inspect_recovery
            from codex_migrate.transport import SSHTransport
            if config.apply:
                raise ValueError("Recovery inspection is read-only; omit --apply. Guided restore is not available yet.")
            result = inspect_recovery(config, SSHTransport(config))
            if args.json:
                print(json.dumps(result, indent=2, sort_keys=True))
            else:
                print(result["message"])
                if result["status"] == "backup_verified":
                    print("Backup items verified: %d" % result["inspected_items"])
                    print("Destination backup: %s" % result["backup"])
            return 0
        if args.command == "export":
            with Cancellation().signals() as cancellation:
                components = args.component or list(SUPPORTED_COMPONENTS)
                state = StateStore(config.state_dir)
                state.acquire_process_lock()
                try:
                    result = ComponentExporter(config, components, cancellation).run()
                finally:
                    state.release_process_lock()
                if args.json:
                    print(json.dumps(result, indent=2, sort_keys=True))
                else:
                    verb = "Exported" if result["applied"] else "Would export"
                    print("%s %d skill component(s)." % (verb, result["item_count"]))
                    print("Components: %s" % ", ".join(result["components"]))
                    for item in result["items"]:
                        print(
                            "- %s [%s] -> %s"
                            % (item["name"], item["scope"], item["destination"])
                        )
                    if not result["applied"]:
                        print("Planning mode only; add --apply to make changes.")
                    else:
                        print("Rollback backup: %s" % result["backup"])
                        print("Restart Codex if the updated skills do not appear automatically.")
                return 0
        state = StateStore(config.state_dir)
        engine = MigrationEngine(config, state)
        if args.command == "inspect":
            state.acquire_process_lock()
            try:
                with Cancellation().signals():
                    result = engine.preflight()
                if args.json:
                    print(json.dumps(result, indent=2, sort_keys=True))
                else:
                    print(result["message"])
                    print("Route: %s" % result["route"])
                    print("Estimated bytes: %d" % result["bytes_total"])
                return 0
            finally:
                state.release_process_lock()
        if args.command == "serve":
            Dashboard(engine, state, port=args.port).serve(open_browser=not args.no_open)
            return 0
        return 2
    except KeyboardInterrupt:
        print("Operation interrupted. No completion is being claimed. Source data "
              "was not changed. Review migration status and backup receipts "
              "before retrying.", file=sys.stderr)
        return 130
    except Exception as error:
        protected = []
        if "args" in locals():
            protected = [
                getattr(args, "identity_file", None) or "",
                getattr(args, "known_hosts_file", None) or "",
            ]
        print("codex-migrate: %s" % redact(str(error), protected), file=sys.stderr)
        return 2
