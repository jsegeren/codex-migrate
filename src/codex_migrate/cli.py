"""Command-line interface for Codex Migrate."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import getpass
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
from codex_migrate.state import StateStore, StateInUseError


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

    vault = commands.add_parser(
        "vault",
        help="Inspect or search local Codex conversation history without changing it",
    )
    vault.add_argument("--source-home", default=str(Path.home()))
    vault_commands = vault.add_subparsers(dest="vault_command", required=True)
    vault_inspect = vault_commands.add_parser("inspect", help="Count locally stored conversations")
    vault_inspect.add_argument("--json", action="store_true")
    vault_search = vault_commands.add_parser("search", help="Search message text in local conversations")
    vault_search.add_argument("query")
    vault_search.add_argument("--limit", type=int, default=25)
    vault_search.add_argument("--json", action="store_true")
    vault_backup = vault_commands.add_parser(
        "backup", help="Create a verified, client-side encrypted conversation backup")
    vault_backup.add_argument("--destination", required=True,
                              help="Absolute path to a new or existing Codex Vault folder")
    vault_backup.add_argument("--crypto-helper",
                              help="Absolute path to the open-source CryptoKit helper")
    vault_backup.add_argument("--chunk-size", type=int, default=4 * 1024 * 1024)
    vault_backup.add_argument("--apply", action="store_true",
                              help="Create and verify a snapshot; otherwise show the plan")
    vault_backup.add_argument("--json", action="store_true")
    vault_verify = vault_commands.add_parser(
        "verify", help="Verify every encrypted object in a Vault snapshot")
    vault_verify.add_argument("--vault", required=True)
    vault_verify.add_argument("--snapshot", default="latest")
    vault_verify.add_argument("--crypto-helper")
    vault_verify.add_argument("--json", action="store_true")
    vault_snapshots = vault_commands.add_parser(
        "snapshots", help="List published backup versions without decrypting content")
    vault_snapshots.add_argument("--vault", required=True)
    vault_snapshots.add_argument("--limit", type=int, default=100)
    vault_snapshots.add_argument("--json", action="store_true")
    vault_restore = vault_commands.add_parser(
        "restore", help="Decrypt a verified snapshot into a separate staging folder")
    vault_restore.add_argument("--vault", required=True)
    vault_restore.add_argument("--output", required=True)
    vault_restore.add_argument("--snapshot", default="latest")
    vault_restore.add_argument("--crypto-helper")
    vault_restore.add_argument("--apply", action="store_true")
    vault_restore.add_argument("--json", action="store_true")
    vault_install = vault_commands.add_parser(
        "install", help="Install a verified snapshot into local Codex with rollback")
    vault_install.add_argument("--vault", required=True)
    vault_install.add_argument("--snapshot", default="latest")
    vault_install.add_argument("--crypto-helper")
    vault_install.add_argument("--apply", action="store_true")
    vault_install.add_argument("--json", action="store_true")
    vault_install_thread = vault_commands.add_parser(
        "install-thread",
        help="Add one missing verified conversation without replacing local history",
    )
    vault_install_thread.add_argument("--vault", required=True)
    vault_install_thread.add_argument("--snapshot", default="latest")
    vault_install_thread.add_argument(
        "--collection", required=True, choices=("active", "archived"))
    vault_install_thread.add_argument(
        "--transcript", required=True,
        help="Exact transcript path shown by Vault search")
    vault_install_thread.add_argument("--crypto-helper")
    vault_install_thread.add_argument("--apply", action="store_true")
    vault_install_thread.add_argument("--json", action="store_true")
    vault_install_status = vault_commands.add_parser(
        "install-status", help="Inspect interrupted local Vault installation state")
    vault_install_status.add_argument("--json", action="store_true")
    vault_install_recover = vault_commands.add_parser(
        "install-recover", help="Roll back an interrupted local Vault installation")
    vault_install_recover.add_argument("--apply", action="store_true")
    vault_install_recover.add_argument("--json", action="store_true")
    vault_import = vault_commands.add_parser(
        "key-import", help="Import a Vault recovery key into this Mac's Keychain")
    vault_import.add_argument("--vault", required=True)
    vault_import.add_argument("--crypto-helper")
    vault_export = vault_commands.add_parser(
        "key-export", help="Display the Vault recovery key for password-manager storage")
    vault_export.add_argument("--vault", required=True)
    vault_export.add_argument("--crypto-helper")
    vault_schedule = vault_commands.add_parser(
        "schedule", help="Create a recurring verified Vault backup on this Mac")
    vault_schedule.add_argument("--vault", required=True)
    vault_schedule.add_argument("--interval-hours", type=int, default=24,
                                choices=(6, 12, 24, 168))
    vault_schedule.add_argument("--crypto-helper")
    vault_schedule.add_argument("--apply", action="store_true")
    vault_schedule.add_argument("--json", action="store_true")
    vault_schedule_status = vault_commands.add_parser(
        "schedule-status", help="Show the automatic Vault backup state")
    vault_schedule_status.add_argument("--json", action="store_true")
    vault_schedule_remove = vault_commands.add_parser(
        "schedule-remove", help="Turn off automatic Vault backups without deleting snapshots")
    vault_schedule_remove.add_argument("--apply", action="store_true")
    vault_schedule_remove.add_argument("--json", action="store_true")
    vault_scheduled_run = vault_commands.add_parser(
        "scheduled-run", help=argparse.SUPPRESS)
    vault_scheduled_run.add_argument("--config", required=True)

    return root


def _migration_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--target", required=True, help="SSH destination, such as user@new-mac.local")
    command.add_argument("--target-home", required=True, help="Absolute destination home directory")
    command.add_argument("--source-home", default=str(Path.home()))
    command.add_argument("--workspace", action="append", default=[])
    command.add_argument("--state-dir", default=str(Path.home() / ".local/state/codex-migrate"))
    command.add_argument("--staging-name", default="Codex-Migrate-Staging",
                         help="Destination staging folder name; keep unchanged when resuming a migration")
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
        staging_name=args.staging_name,
        apply=args.apply,
        compress=not args.no_compress,
        ssh=SSHOptions(
            identity_file=args.identity_file,
            known_hosts_file=args.known_hosts_file,
            host_key_alias=args.host_key_alias,
        ),
    ).validate()


@contextmanager
def _bound_state(config: MigrationConfig, components=None):
    # No credential paths or contents. Apply/compression may change on resume;
    # data scope and destination may not. SSH host verification remains separate.
    binding = {"version": 1, "source_home": config.source_home,
               "target": config.target, "target_home": config.target_home,
               "workspace_roots": sorted(config.workspace_roots),
               "staging_name": config.staging_name, "backup_prefix": config.backup_prefix,
               "mode": "export" if components is not None else "full",
               "components": sorted(set(components or []))}
    state = StateStore(config.state_dir)
    state.acquire_process_lock()
    try:
        state.bind_configuration(binding)
        yield state
    finally:
        state.release_process_lock()


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
        if args.command == "vault":
            from codex_migrate.vault import inspect as inspect_vault, search as search_vault
            if args.vault_command in (
                    "schedule", "schedule-status", "schedule-remove", "scheduled-run"):
                from codex_migrate.vault_schedule import (
                    install_schedule, plan_schedule, remove_schedule,
                    run_scheduled_backup, schedule_status,
                )
                if args.vault_command == "scheduled-run":
                    return run_scheduled_backup(args.config)
                if args.vault_command == "schedule-status":
                    result = schedule_status(args.source_home)
                elif args.vault_command == "schedule-remove":
                    if not args.apply:
                        result = {"enabled": schedule_status(args.source_home).get("enabled", False),
                                  "applied": False}
                    else:
                        result = remove_schedule(args.source_home)
                        result["applied"] = True
                else:
                    result = (install_schedule(
                        args.source_home, args.vault,
                        interval_hours=args.interval_hours,
                        crypto_helper=args.crypto_helper,
                    ) if args.apply else plan_schedule(
                        args.source_home, args.vault,
                        interval_hours=args.interval_hours,
                        crypto_helper=args.crypto_helper,
                    ))
                    result = result.as_dict()
                if args.json:
                    print(json.dumps(result, indent=2, sort_keys=True))
                elif args.vault_command == "schedule":
                    if result["applied"]:
                        print("Automatic verified backup enabled every %d hour(s)." % result["interval_hours"])
                    else:
                        print("Would enable an automatic verified backup every %d hour(s)." % result["interval_hours"])
                        print("Planning mode only; add --apply to install the macOS schedule.")
                    print("Vault: %s" % result["vault"])
                elif args.vault_command == "schedule-remove":
                    print("Automatic backup is off." if result["applied"] else
                          "Would turn off automatic backups without deleting Vault snapshots.")
                else:
                    print("Automatic backup: %s" % ("on" if result.get("enabled") else "off"))
                    if result.get("enabled"):
                        print("Healthy: %s" % ("yes" if result.get("healthy") else "no"))
                        print("Every %d hour(s)" % result["interval_hours"])
                        print("Vault: %s" % result["vault"])
                return 0
            if args.vault_command == "inspect":
                result = inspect_vault(args.source_home)
                if args.json:
                    print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
                else:
                    print("Active conversations: %d" % result.active_transcripts)
                    print("Archived conversations: %d" % result.archived_transcripts)
                    print("Transcript bytes: %d" % result.transcript_bytes)
                return 0
            if args.vault_command == "backup":
                from codex_migrate.vault_backup import backup as backup_vault, plan as plan_vault
                result = (backup_vault(
                    args.source_home, args.destination,
                    crypto_helper=args.crypto_helper, chunk_size=args.chunk_size,
                ) if args.apply else plan_vault(args.source_home, args.destination))
                if args.json:
                    print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
                else:
                    if result.applied:
                        print("Verified snapshot: %s" % result.snapshot_id)
                        print("Conversation files: %d" % result.transcript_files)
                        print("Plaintext bytes protected: %d" % result.transcript_bytes)
                        print("Encrypted chunks: %d" % result.chunks)
                        print("Vault: %s" % result.destination)
                        if result.recovery_key:
                            print("RECOVERY KEY (save in a password manager; shown once):")
                            print(result.recovery_key)
                    else:
                        print("Would back up %d conversation file(s), %d byte(s)." % (
                            result.transcript_files, result.transcript_bytes))
                        print("Destination: %s" % result.destination)
                        print("Client-side authenticated encryption: required")
                        print("Planning mode only; add --apply to create a verified snapshot.")
                return 0
            if args.vault_command in (
                    "install", "install-thread", "install-status", "install-recover"):
                from codex_migrate.vault_install import (
                    install_snapshot, install_status, install_thread, plan_install,
                    plan_thread_install,
                    recover_interrupted_install,
                )
                if args.vault_command == "install-status":
                    result = install_status(args.source_home)
                elif args.vault_command == "install-recover":
                    result = recover_interrupted_install(
                        args.source_home, apply=args.apply)
                elif args.vault_command == "install-thread":
                    function = install_thread if args.apply else plan_thread_install
                    result = function(
                        args.source_home, args.vault, args.collection,
                        args.transcript, snapshot=args.snapshot,
                        crypto_helper=args.crypto_helper,
                    )
                elif args.apply:
                    result = install_snapshot(
                        args.source_home, args.vault, snapshot=args.snapshot,
                        crypto_helper=args.crypto_helper)
                else:
                    result = plan_install(
                        args.source_home, args.vault, snapshot=args.snapshot,
                        crypto_helper=args.crypto_helper)
                payload = result if isinstance(result, dict) else result.as_dict()
                if args.json:
                    print(json.dumps(payload, indent=2, sort_keys=True))
                elif args.vault_command == "install-status":
                    print("Vault installation status: %s" % payload["status"])
                    if payload.get("backup"):
                        print("Rollback backup: %s" % payload["backup"])
                elif args.vault_command == "install-recover":
                    print("Vault installation recovery: %s" % payload["status"])
                    if not payload.get("applied") and payload["status"] != "idle":
                        print("Planning mode only; add --apply to verify rollback.")
                elif args.vault_command == "install-thread":
                    if payload.get("applied"):
                        print("Recovered one verified conversation: %s" % payload["transcript"])
                        print("Installed at: %s" % payload["target"])
                        print("Unrelated Codex history was not changed.")
                        print("Receipt: %s" % payload["receipt"])
                    elif payload.get("status") == "already_present" or \
                            payload.get("action") == "already_present":
                        print("Conversation is already present: %s" % payload["target"])
                        print("No local history was changed.")
                    else:
                        print("Would add one verified conversation: %s" % payload["transcript"])
                        print("Target: %s" % payload["target"])
                        print("Planning mode only; add --apply after closing Codex.")
                elif payload.get("applied"):
                    print("Installed verified snapshot: %s" % payload["snapshot_id"])
                    print("Conversation files: %d" % payload["transcript_files"])
                    print("Rollback backup: %s" % payload["backup"])
                    print("Authentication and installation identity were not changed.")
                else:
                    print("Would install verified snapshot: %s" % payload["snapshot_id"])
                    print("Conversation files: %d" % payload["transcript_files"])
                    print("Close Codex before applying. Planning mode only; add --apply.")
                return 0
            if args.vault_command in (
                    "verify", "restore", "snapshots", "key-import", "key-export"):
                from codex_migrate.vault_recovery import (
                    export_recovery_key, import_recovery_key, list_snapshots,
                    plan_restore, restore_snapshot, verify_snapshot,
                )
                if args.vault_command == "key-import":
                    recovery_key = getpass.getpass(
                        "Vault recovery key (input hidden; not stored in shell history): ")
                    key_id = import_recovery_key(
                        args.vault, recovery_key, crypto_helper=args.crypto_helper)
                    print("Recovery key imported into this Mac's Keychain: %s" % key_id)
                    return 0
                if args.vault_command == "key-export":
                    print("RECOVERY KEY (store in a password manager):")
                    print(export_recovery_key(args.vault, crypto_helper=args.crypto_helper))
                    return 0
                if args.vault_command == "snapshots":
                    snapshots = list_snapshots(args.vault, limit=args.limit)
                    if args.json:
                        print(json.dumps(
                            [item.as_dict() for item in snapshots],
                            indent=2, sort_keys=True))
                    else:
                        for item in snapshots:
                            marker = " (latest)" if item.latest else ""
                            print("%s · %s%s" % (
                                item.created_at, item.snapshot_id, marker))
                    return 0
                if args.vault_command == "verify":
                    result = verify_snapshot(
                        args.vault, snapshot=args.snapshot,
                        crypto_helper=args.crypto_helper)
                elif args.apply:
                    result = restore_snapshot(
                        args.source_home, args.vault, args.output,
                        snapshot=args.snapshot, crypto_helper=args.crypto_helper)
                else:
                    result = plan_restore(
                        args.source_home, args.vault, args.output,
                        snapshot=args.snapshot, crypto_helper=args.crypto_helper)
                if args.json:
                    print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
                else:
                    print("Verified snapshot: %s" % result.snapshot_id)
                    print("Conversation files: %d" % result.transcript_files)
                    print("Plaintext bytes protected: %d" % result.transcript_bytes)
                    if result.applied:
                        print("Restored to staging folder: %s" % result.output)
                        print("Live Codex data was not changed.")
                    elif args.vault_command == "restore":
                        print("Would restore to: %s" % result.output)
                        print("Planning mode only; add --apply to stage recovered files.")
                    else:
                        print("Encrypted chunks: %d" % result.chunks)
                return 0
            results = search_vault(args.source_home, args.query, args.limit)
            if args.json:
                print(json.dumps([item.as_dict() for item in results], indent=2, sort_keys=True))
            else:
                for item in results:
                    when = " (%s)" % item.timestamp if item.timestamp else ""
                    print("%s · %s:%d%s" % (
                        item.collection, item.transcript, item.line, when))
                    print("  %s" % item.snippet)
                if not results:
                    print("No matching conversation text found.")
            return 0

        config = _config(args)
        if args.command == "recovery":
            from codex_migrate.recovery import inspect_recovery
            from codex_migrate.transport import SSHTransport
            if config.apply:
                raise ValueError("Recovery inspection is read-only; omit --apply. Use the browser recovery panel for confirmed restoration.")
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
                with _bound_state(config, components):
                    result = ComponentExporter(config, components, cancellation).run()
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
        with _bound_state(config) as state:
            engine = MigrationEngine(config, state)
            if args.command == "inspect":
                with Cancellation().signals():
                    result = engine.preflight()
                if args.json:
                    print(json.dumps(result, indent=2, sort_keys=True))
                else:
                    print(result["message"])
                    print("Route: %s" % result["route"])
                    print("Estimated bytes: %d" % result["bytes_total"])
                return 0
            if args.command == "serve":
                Dashboard(engine, state, port=args.port).serve(open_browser=not args.no_open)
                return 0
        return 2
    except StateInUseError:
        print("codex-migrate: another Codex Migrate process is already using this state directory", file=sys.stderr)
        return 75
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
