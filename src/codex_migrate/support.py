"""Opt-in diagnostics: construct from an allowlist, never export raw logs."""

from datetime import datetime, timezone
from html import escape
import platform
import re
import json
from pathlib import Path
import sys
from urllib.parse import quote, urlencode

from codex_migrate import __version__

SUPPORT_EMAIL = "joshua@segeren.com"
SUPPORT_URL = "mailto:" + SUPPORT_EMAIL + "?" + urlencode({
    "subject": "Codex Migrate support",
    "body": "What happened, and what were you trying to do?\r\n\r\n"
            "App/macOS versions (if known):\r\n\r\n"
            "Please attach the diagnostic report after reviewing it. "
            "Do not send passwords, keys, conversations, or workspace contents.\r\n",
}, quote_via=quote)
STATUSES = frozenset(("idle", "ready", "running", "paused", "cancelled", "failed",
                      "interrupted", "waiting", "ready_to_finalize", "complete"))
PHASES = frozenset(("not_started", "inspecting", "preflight_complete", "staging",
                    "staged", "close_source_codex", "close_target_codex", "final_delta",
                    "verifying_sources", "installing", "verified"))
FAILURES = frozenset(("none", "unknown", "disk_space", "connection", "permissions",
                      "verification", "process_guard", "interrupted", "git_scope", "machine_identity", "destination_lock", "recovery_pending"))
HISTORY_LIMIT = 60


def failure_category(error):
    if not error:
        return "none"
    # Only the fixed category leaves this function, never matching text/paths.
    text = str(error).lower()
    for category, terms in (
        ("recovery_pending", ("unfinished destination installation", "recovery evidence", "rollback is unconfirmed")),
        ("destination_lock", ("another migration is using this destination", "cannot safely lock the destination")),
        ("machine_identity", ("machine identity", "machine identities", "destination is this source mac")),
        ("disk_space", ("not enough", "insufficient space", "no space left", "disk full", "space check")),
        ("connection", ("ssh", "connection", "timed out", "host key", "rsync exited")),
        ("permissions", ("permission", "access denied")),
        ("verification", ("verification", "checksum", "receipt", "integrity")),
        ("process_guard", ("process state", "close codex", "codex is open")),
        ("interrupted", ("interrupt", "shutdown")),
        ("git_scope", ("git dependenc", "git metadata")),
    ):
        if any(term in text for term in terms):
            return category
    return "unknown"


def _enum(value, allowed):
    return value if isinstance(value, str) and value in allowed else "unknown"


def event_fields(state):
    return {"status": _enum(state.get("status"), STATUSES),
            "phase": _enum(state.get("phase"), PHASES),
            "failure_category": failure_category(state.get("error")),
            "space_check": _enum(state.get("space_check"), {"passed", "blocked"})}


def _number(value):
    return value if type(value) is int and 0 <= value <= 2**63 - 1 else None


def _build_identity():
    result = {"source_revision": None, "bundle_version": None, "mode": "source"}
    if not getattr(sys, "frozen", False):
        return result
    result["mode"] = "unknown"
    try:
        metadata = Path(sys.executable).parent.parent / "build-info.json"
        with metadata.open(encoding="utf-8") as stream:
            value = json.loads(stream.read(16384))
        if not isinstance(value, dict):
            return result
        revision = value.get("source_revision")
        build = value.get("bundle_version")
        result["source_revision"] = revision if isinstance(revision, str) and re.fullmatch(r"[0-9a-f]{40,64}", revision) else None
        result["bundle_version"] = build if isinstance(build, str) and re.fullmatch(r"[0-9]{1,9}", build) else None
        result["mode"] = _enum(value.get("build_mode"), {"release", "local-test"})
    except (OSError, ValueError):
        pass
    return result


def diagnostic_report(state):
    state = state if isinstance(state, dict) else {}
    receipt = state.get("receipt")
    receipt = receipt if isinstance(receipt, dict) else {}
    history = state.get("support_history")
    history = history if isinstance(history, list) else []
    events = []
    for item in history[-HISTORY_LIMIT:]:
        if not isinstance(item, dict):
            continue
        timestamp = item.get("at")
        events.append({
            "at": timestamp if isinstance(timestamp, str) and re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", timestamp) else None,
            "status": _enum(item.get("status"), STATUSES),
            "phase": _enum(item.get("phase"), PHASES),
            "failure_category": _enum(item.get("failure_category"), FAILURES),
            "space_check": _enum(item.get("space_check"), {"passed", "blocked"}),
        })
    macos = platform.mac_ver()[0]
    return {
        "report_format": 1,
        "app_version": __version__,
        "build": _build_identity(),
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "macos_version": macos if re.fullmatch(r"\d+(?:\.\d+){0,2}", macos) else "unknown",
        "architecture": _enum(platform.machine(), {"arm64", "x86_64"}),
        "migration_mode": _enum(state.get("migration_mode", "full"), {"full", "skills"}),
        "current": event_fields(state),
        "sizes_bytes": {key: _number(state.get(key)) for key in (
            "bytes_total", "bytes_staged", "destination_bytes_free",
            "destination_bytes_required", "backup_bytes_required")},
        "staging_complete": state.get("staging_complete") is True,
        "pending_backup_recorded": bool(state.get("pending_backup")),
        "verification": {key: receipt.get(key) if type(receipt.get(key)) is bool else None
                         for key in ("backup_verified", "conversation_content_verified",
                                     "codex_state_content_verified", "workspace_content_verified",
                                     "auth_preserved", "installation_id_preserved")},
        "recent_events": events,
        "notes": "Structured diagnostic log, not raw command output. History is limited to "
                 "60 transitions recorded by this version; earlier runs may have none. "
                 "Failure categories are hints, not diagnoses. No automatic upload.",
    }


SUPPORT_CSS = """
.support-link { display:inline-block; padding:12px 15px; border:1px solid #a08bd3;
  border-radius:10px; color:#f7f8fa; background:#6042a6; font-size:16px;
  font-weight:700; text-decoration:underline; line-height:1.4; }
a:focus-visible,button:focus-visible,textarea:focus-visible {
  outline:3px solid #d9cdff; outline-offset:4px; }
#migration-help { margin-top:20px; padding:20px; border:1px solid #8996ad;
  border-radius:12px; color:#f7f8fa; background:#111722; font-size:16px; }
#migration-help h2 { margin-top:0; font-size:24px; }
summary { cursor:pointer; padding:10px 0; font-size:16px; font-weight:600; }
summary:focus-visible { outline:3px solid #d9cdff; outline-offset:4px; }
#migration-help a { color:#d9cdff; overflow-wrap:anywhere; }
#migration-help .controls { display:flex; flex-wrap:wrap; gap:12px; }
#migration-help textarea { display:block; width:100%; min-height:220px; margin:12px 0;
  padding:12px; color:#f7f8fa; background:#080b10; border:1px solid #8996ad;
  font:15px/1.5 ui-monospace,monospace; }
#migration-help [hidden] { display:none!important; }
"""

SUPPORT_HTML = """<section id="migration-help" aria-labelledby="support-heading">
<h2 id="support-heading">Need a hand?</h2>
<p>Contact Josh at <a href="{url}">{email}</a>. Keep your source data, staging, and backups.</p>
<div class="controls"><button type="button" id="prepare-support">Prepare diagnostic report</button>
<a class="support-link" href="{url}">Email support</a></div>
<p>Review the report, save it, then attach it to your email. Nothing is uploaded automatically.</p>
<details><summary>What’s in the report?</summary><p>App/macOS versions, sizes, recent phases,
failure categories, and verification flags. No conversations, credentials, filenames, private paths,
or raw command output. You can inspect the report before sharing.</p></details>
<details><summary>Recovery and support details</summary>
<p>During copying, use Stop safely before quitting. During installation, let it finish;
if it fails, keep Codex closed on the new Mac and ask for help before replacing anything.</p>
<p>We’ll make a best-effort attempt to help, aiming for an initial reply within a few business days.
Response times and fixes aren’t guaranteed. If no email app opens, copy the address above into your usual email service.</p></details>
<p id="support-status" role="status" aria-live="polite"></p>
<div id="support-preview" hidden><label for="support-report">Review the report before sharing</label>
<textarea id="support-report" readonly spellcheck="false"></textarea>
<button type="button" id="save-support">Save report to attach</button></div>
</section>""".format(url=escape(SUPPORT_URL, quote=True), email=SUPPORT_EMAIL)

SUPPORT_SCRIPT = r"""
let reviewedSupportReport=null;
document.getElementById('prepare-support').onclick=async()=>{
  const button=document.getElementById('prepare-support');button.disabled=true;
  reviewedSupportReport=null;document.getElementById('support-preview').hidden=true;
  document.getElementById('support-status').textContent='Preparing a local diagnostic report…';
  try {
    const response=await fetch('/api/support-report',{headers:{'X-Codex-Migrate-Token':token}});
    if(!response.ok)throw Error('Report unavailable');
    reviewedSupportReport=JSON.stringify(await response.json(),null,2)+'\n';
    document.getElementById('support-report').value=reviewedSupportReport;
    document.getElementById('support-preview').hidden=false;
    document.getElementById('support-status').textContent='Review, save, and manually attach this report to your email. It has not been sent.';
    const preview=document.getElementById('support-report');
    preview.setSelectionRange(0,0);preview.focus();preview.scrollTop=0;
  } catch (_) {
    document.getElementById('support-status').textContent='The helper could not prepare a report. You can still email support. Describe the visible phase and what happened; do not send private paths or credentials.';
  } finally {button.disabled=false;}
};
document.getElementById('save-support').onclick=()=>{
  if(reviewedSupportReport===null)return;
  const url=URL.createObjectURL(new Blob([reviewedSupportReport],{type:'application/json'}));
  const link=document.createElement('a');link.href=url;link.download='codex-migrate-diagnostics.json';
  document.body.appendChild(link);link.click();link.remove();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
  document.getElementById('support-status').textContent='Report download requested. Attach the saved file to your email; no email or upload was sent automatically.';
};
"""


def with_support(document):
    return document.replace("</style>", SUPPORT_CSS + "</style>", 1).replace(
        "<footer>", SUPPORT_HTML + "<footer>", 1).replace(
        "</script>", SUPPORT_SCRIPT + "</script>", 1)
