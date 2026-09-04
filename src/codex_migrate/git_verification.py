"""Private, installation-bound Git baselines and read-only destination checks.

Only the summary returned by check_installed is suitable for UI/diagnostics.
The baseline contains private paths and opaque hashes: keep it in owner-only
state, never in a support attachment or public status response.
"""

import hashlib
import json
from pathlib import Path
import re
import secrets

from codex_migrate.errors import MigrationError
from codex_migrate.git_inventory import inspect_git
from codex_migrate.git_probe import PROBE_TIMEOUT, parse_report, probe_local, probe_script
from codex_migrate.destination_lock import readonly_destination_script


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode("ascii")).hexdigest()


def require_runtime(home, transport=None, cancelled=lambda: False):
    """Preflight only: check the guarded executable with no repository read grants."""
    def checkpoint():
        if cancelled():
            raise MigrationError("Git readiness check stopped")
    checkpoint()
    try:
        if transport is None:
            report = probe_local(home, [], [], checkpoint)
        else:
            result = transport.run_remote_cancellable(
                probe_script(home, [], []), timeout=PROBE_TIMEOUT, cancelled=cancelled)
            report = parse_report(result.stdout, 0)
        checkpoint()
        return report["git_version"]
    except Exception as error:
        checkpoint()
        side = "source" if transport is None else "destination"
        raise MigrationError(
            "Git verification is unavailable on the %s Mac. Transfer is blocked. "
            "Check the Apple Command Line Tools/Xcode installation, then inspect again; "
            "contact support if it is already installed. No files were changed by this check." % side
        ) from error


def source_plan(config, checkpoint):
    plan = inspect_git(config.source_home, config.workspace_roots, checkpoint)
    if plan.issues or plan.missing_paths:
        raise MigrationError("Git storage scope changed or needs review. Inspect the selected folders before installing.")
    roots = list(config.workspace_roots)
    managed = Path(config.source_codex) / "worktrees"
    if managed.exists() or managed.is_symlink():
        roots.append(str(managed))
    # Never grant the whole .codex directory, which contains protected identity.
    # Dependencies in other retained Codex folders may therefore need review.
    return {"roots": roots, "repositories": plan.repositories}


def freeze_baseline(config, migration_id, prepared, checkpoint):
    if not isinstance(migration_id, str) or not re.fullmatch(r"[0-9a-f]{32}", migration_id):
        raise MigrationError("Cannot bind Git checks to this migration's staging ownership")
    plan = source_plan(config, checkpoint)
    checkpoint()
    report = None
    if plan["repositories"]:
        try:
            report = probe_local(config.source_home, plan["roots"], plan["repositories"], checkpoint)
        except MigrationError:
            # A missing Git installation/unsupported layout is not copy damage.
            # A cancellation must still stop finalization, never become a warning.
            checkpoint()
            raise MigrationError("The source Git baseline could not be saved. Finalization stopped before replacement; staging and the destination were kept. Resolve Git verification, choose Resume to refresh staging, then Finalize.") from None
    checkpoint()
    return {"format": 1, "attempt": secrets.token_hex(16), "migration_id": migration_id,
            "source_home": config.source_home, "target_home": config.target_home,
            "workspace_roots": list(config.workspace_roots), "plan": plan,
            "content": fingerprint(prepared), "report": report}


def validate_baseline(config, state):
    baseline, receipt = state.get("git_baseline"), state.get("receipt")
    try:
        if not isinstance(baseline, dict) or set(baseline) != {
                "format", "attempt", "migration_id", "source_home", "target_home",
                "workspace_roots", "plan", "content", "report"}:
            raise ValueError()
        if type(baseline["format"]) is not int or baseline["format"] != 1:
            raise ValueError()
        for key in ("attempt", "migration_id"):
            if not isinstance(baseline[key], str) or not re.fullmatch(r"[0-9a-f]{32}", baseline[key]):
                raise ValueError()
        if (baseline["migration_id"] != state.get("migration_id")
                or baseline["source_home"] != config.source_home
                or baseline["target_home"] != config.target_home
                or baseline["workspace_roots"] != list(config.workspace_roots)
                or not re.fullmatch(r"[0-9a-f]{64}", baseline["content"])
                or receipt.get("git_baseline_id") != fingerprint(baseline)
                or receipt.get("migration_id") != baseline["migration_id"]
                or not installation_verified(config, receipt)):
            raise ValueError()
        plan = baseline["plan"]
        if not isinstance(plan, dict) or set(plan) != {"roots", "repositories"}:
            raise ValueError()
        if not isinstance(plan["roots"], list) or not isinstance(plan["repositories"], list):
            raise ValueError()
        allowed = list(config.workspace_roots) + [config.source_codex + "/worktrees"]
        if (plan["roots"] not in (list(config.workspace_roots), allowed)
                or len(plan["repositories"]) > 10000):
            raise ValueError()
        seen = set()
        for repo in plan["repositories"]:
            if not isinstance(repo, dict) or set(repo) != {"path", "git_dir", "kind"}:
                raise ValueError()
            if repo["kind"] not in ("checkout", "linked", "storage"):
                raise ValueError()
            for key in ("path", "git_dir"):
                value = repo[key]
                relative = Path(value).relative_to(config.source_home)
                if (not isinstance(value, str) or not relative.parts or str(Path(value)) != value
                        or ".." in relative.parts or any(ord(c) < 32 or ord(c) == 127 for c in value)):
                    raise ValueError()
            if repo["path"] in seen:
                raise ValueError()
            seen.add(repo["path"])
        if baseline["report"] is not None:
            parse_report(json.dumps(baseline["report"]), len(plan["repositories"]))
        return baseline
    except (ValueError, TypeError, AttributeError, KeyError, MigrationError) as error:
        raise MigrationError("The original Git baseline is missing or does not match this installation. Keep the backup; contact support. No files were changed.") from error


def installation_verified(config, receipt):
    return (isinstance(receipt, dict)
            and all(receipt.get(key) is True for key in (
                "backup_verified", "auth_preserved", "installation_id_preserved",
                "conversation_content_verified", "codex_state_content_verified", "workspace_content_verified"))
            and receipt.get("source_home") == config.source_home
            and receipt.get("target_home") == config.target_home)


def check_installed(config, state, transport, cancelled):
    baseline = validate_baseline(config, state)
    plan = baseline["plan"]
    total = len(plan["repositories"])
    if cancelled():
        return summary("cancelled", total, "Git check stopped. No files were changed; check again when ready.")
    if not total:
        return summary("verified", 0, "No Git repositories were discovered in the selected folders. Workspace content verification is separate.")
    source = baseline["report"]
    if source is None:
        return summary("unavailable", total, "Git could not be checked on the source before installation. The original baseline cannot be recreated by retrying. Files were verified separately; keep the backup and contact support.")

    def mapped(path):
        return str(Path(config.target_home) / Path(path).relative_to(config.source_home))

    repositories = [{**repo, "path": mapped(repo["path"]), "git_dir": mapped(repo["git_dir"])}
                    for repo in plan["repositories"]]
    script = probe_script(config.target_home, [mapped(path) for path in plan["roots"]], repositories)
    try:
        result = transport.run_remote_cancellable(
            readonly_destination_script(config.target_home, script), timeout=PROBE_TIMEOUT, cancelled=cancelled)
        destination = parse_report(result.stdout, total)
    except Exception:
        if cancelled():
            return summary("cancelled", total, "Git check stopped. No files were changed; check again when ready.")
        return summary("unavailable", total, "Destination Git could not be checked safely. Check Git installation and the connection, then try Check Git again. No files were changed.")
    if cancelled():
        return summary("cancelled", total, "Git check stopped. No files were changed; check again when ready.")
    counts = {"matched": 0, "changed": 0, "source_needs_review": 0, "destination_needs_review": 0, "shallow": 0}
    for old, new in zip(source["repositories"], destination["repositories"]):
        if old["status"] != "checked":
            counts["source_needs_review"] += 1
        elif new["status"] != "checked":
            counts["destination_needs_review"] += 1
        elif old != new:
            counts["changed"] += 1
        else:
            counts["matched"] += 1
        if old.get("history_scope") == "shallow" or new.get("history_scope") == "shallow":
            counts["shallow"] += 1
    verified = counts["matched"] == total
    message = ("Git checks match the source baseline for all %d location(s). This is a point-in-time local check, not a test of future development commands." % total
               if verified else "Git needs review: %d matched, %d changed since the baseline, %d had source issues, %d could not be checked on the destination. Changes may be your new work; nothing was recopied or restored." % (
                   counts["matched"], counts["changed"], counts["source_needs_review"], counts["destination_needs_review"]))
    if counts["shallow"]:
        message += " Shallow history is not complete remote history."
    return {**summary("verified" if verified else "needs_review", total, message), **counts}


def summary(status, total, message):
    return {"status": status, "total": total, "message": message}
