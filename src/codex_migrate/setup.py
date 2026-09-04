"""Browser-first setup, local persistence and native folder selection.

This server never proxies workspace contents. It attaches the same Dashboard
and MigrationEngine used by the CLI after explicit validated configuration.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
import subprocess
import threading

from codex_migrate.config import MigrationConfig, SSHOptions
from codex_migrate.dashboard import Dashboard
from codex_migrate.migration import MigrationEngine, MigrationError
from codex_migrate.state import StateStore


SETUP_HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="data:,"><title>Set up your migration — Codex Migrate</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#080b10;color:#f7f8fa;font:500 17px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;overflow-wrap:anywhere}
main{width:min(800px,calc(100% - 32px));margin:40px auto}h1{font-size:clamp(32px,6vw,48px);line-height:1.1}h2{font-size:24px}p{color:#cbd2df}section,fieldset{background:#111722;border:1px solid #465268;border-radius:16px;padding:24px;margin:24px 0;min-width:0}
label{display:block;margin:16px 0 6px}input,textarea,button{font:inherit}input:not([type=checkbox]),textarea{display:block;width:100%;padding:12px;border:1px solid #8996ad;border-radius:8px;color:#f7f8fa;background:#080b10}textarea{min-height:120px}button,a.button{display:inline-block;padding:12px 18px;border:1px solid #a08bd3;border-radius:9px;background:#6042a6;color:white;font-weight:700;cursor:pointer;text-decoration:none;max-width:100%;white-space:normal}button:disabled{opacity:.6;cursor:wait}.controls{display:flex;gap:12px;flex-wrap:wrap}.check{display:flex;gap:12px;align-items:flex-start}.check input{width:22px;height:22px;flex:none;margin-top:4px}a{color:#d9cdff}:focus-visible{outline:3px solid #d9cdff;outline-offset:4px}#error{color:#ffc3c8}#message{color:#cbd2df}footer{font-size:15px;color:#cbd2df}legend{font-weight:700;font-size:24px}[hidden]{display:none!important}@media(max-width:480px){section,fieldset{padding:16px}main{margin:24px auto}}
</style></head><body><main>
<h1>Keep the work. Change the Mac.</h1><p>Set up your Mac-to-Mac migration here. This page is served by the helper on your old Mac. Your workspace travels directly between your Macs over SSH—not through our website.</p>
<div id="error" role="alert"></div><p id="message" role="status" aria-live="polite">Connecting to your local helper…</p>
<section id="attached" hidden><h2>Your migration is configured</h2><p>Continue to its status, backup checks, pause/resume controls and recovery guidance. Keep the same destination and scope when resuming. Changing scope while staged data exists requires reviewing that migration’s recovery instructions; restarting alone does not adopt it.</p><a class="button" id="continue" href="/migration">Open migration dashboard</a></section>
<form id="setup"><fieldset id="fields" disabled><legend>1 · Prepare the new Mac</legend>
<p>Install Codex, open it, and sign in once on the new Mac. Enable Remote Login in System Settings → General → Sharing for your account. Keep an independent backup and leave your old Mac intact.</p>
<p>Wi-Fi or a compatible USB-C/Thunderbolt network connection can carry the transfer. A charging-only cable cannot. Both Macs must remain awake and connected.</p>
<details><summary>SSH connection and permissions</summary><p>Set up SSH key login from the old Mac and verify the new Mac’s host fingerprint through a trusted channel. Connect once in Terminal using <code>ssh new-user@new-mac.local</code>. We never disable host verification. The helper cannot answer an interactive password prompt.</p></details>
<h2>2 · Destination and scope</h2>
<label for="target">New Mac’s SSH address</label><input id="target" autocomplete="off" placeholder="new-user@new-mac.local" required>
<label for="target-home">New Mac’s home folder</label><input id="target-home" autocomplete="off" placeholder="/Users/new-user" required>
<p>Use the new Mac’s exact username and home folder; they can differ from the old Mac. Check with <code>whoami</code> and <code>echo "$HOME"</code> in its Terminal.</p>
<label for="workspaces">Workspace folders on this Mac, one per line</label><textarea id="workspaces" spellcheck="false" aria-describedby="scope-help"></textarea>
<p id="scope-help">Selected folders include complete Git metadata and unfinished work, including secrets stored inside them. Leave this empty to migrate Codex state and discovered personal custom skills without project folders. Personal skills from .agents/skills and legacy .codex/skills are included automatically; inspection lists them before transfer. Other home folders are not automatically included.</p>
<div class="controls"><button type="button" id="folders">Choose folders on this Mac…</button><button type="button" id="suggest">Suggest common folders</button></div>
<label for="identity">Existing SSH key path (optional)</label><input id="identity" autocomplete="off" spellcheck="false" aria-describedby="key-help"><p id="key-help">Leave empty to use your SSH configuration. Selecting a key does not add it to the migration, and this selection is not saved. A key stored inside a selected workspace is copied with that workspace.</p>
<h2>3 · Review before enabling changes</h2><p>Your last configured destination and selected roots are saved privately on this Mac for reopening. Changes reset to disabled on each launch. A verified destination backup is mandatory before replacement; insufficient space blocks installation.</p>
<label class="check"><input id="apply" type="checkbox"><span>Enable destination changes for this session. Opening the dashboard does not start a transfer; I will inspect and start it explicitly.</span></label>
<button type="submit" id="open">Open migration dashboard</button>
</fieldset></form>
<section><h2>Recovery and selective exports</h2><p>For migrations started in this browser setup, reopen the helper after interruption, review the restored setup, enable changes if appropriate, and use Resume in the dashboard. Staged data and backup receipts remain on your Macs. Never delete them just because a progress bar reaches 100%.</p><p>Already started with the CLI or native setup? Resume using that same entry point and configuration. This browser setup does not import those older migration records, and it will not adopt or overwrite their staging.</p><p>For a skills-only repair, the native app’s skills controls and the CLI export command remain available. This browser setup currently configures full migrations.</p></section>
<footer>Codex Migrate is independent software. Not affiliated with or endorsed by OpenAI. Mac-to-Mac only.</footer>
</main><script>
const $=id=>document.getElementById(id);
const storageKey="codex-migrate-token:"+location.origin;
const incoming=new URLSearchParams(location.hash.slice(1)).get("token");
if(incoming)sessionStorage.setItem(storageKey,incoming);
const token=incoming||sessionStorage.getItem(storageKey)||"";
history.replaceState(null,"",location.pathname);
const roots=()=>$("workspaces").value.split("\n").map(x=>x.trim()).filter(Boolean);
async function api(path,body){const r=await fetch(path,{method:body?"POST":"GET",headers:{"X-Codex-Migrate-Token":token,"Content-Type":"application/json"},...(body?{body:JSON.stringify(body)}:{})});const result=await r.json();if(!r.ok)throw Error(result.error||"The request failed");return result}
function attached(){ $("attached").hidden=false;$("setup").hidden=true;$("continue").href="/migration#token="+encodeURIComponent(token);$("message").textContent="The helper is ready. No transfer was started automatically."; }
async function load(){try{const s=await api("/api/setup");if(s.attached){attached();return}const c=s.saved||{};$("target").value=c.target||"";$("target-home").value=c.target_home||"";$("workspaces").value=(c.workspace_roots||[]).join("\n");$("apply").checked=false;$("fields").disabled=false;$("message").textContent=s.saved?"Restored your last setup. Review it before continuing; changes remain disabled.":"Ready to configure. No destination changes are enabled."}catch(e){$("error").textContent=e.message+". Reopen the browser from the local helper if its token is missing."}}
async function folders(path){$("folders").disabled=true;$("suggest").disabled=true;try{const r=await api(path,{});$("workspaces").value=[...new Set([...roots(),...r.paths])].join("\n");$("message").textContent=r.message}catch(e){$("error").textContent=e.message}finally{$("folders").disabled=false;$("suggest").disabled=false}}
$("folders").onclick=()=>folders("/api/folders");$("suggest").onclick=()=>folders("/api/suggestions");
$("setup").onsubmit=async e=>{e.preventDefault();$("open").disabled=true;$("error").textContent="";try{await api("/api/setup",{target:$("target").value.trim(),target_home:$("target-home").value.trim(),workspace_roots:roots(),identity_file:$("identity").value.trim(),apply:$("apply").checked});location.href="/migration#token="+encodeURIComponent(token)}catch(e){$("error").textContent=e.message;$("open").disabled=false}};
load();
</script></body></html>'''


class SetupDashboard(Dashboard):
    def __init__(self, source_home: str, state_dir: str, port: int = 0):
        self.source_home = str(Path(source_home).resolve())
        # Reuse config confinement without persisting a fictitious destination.
        validated = MigrationConfig(target="setup@localhost", target_home="/Users/setup",
                                    source_home=self.source_home, state_dir=state_dir).validate()
        self.registry = StateStore(validated.state_dir)
        self.registry.acquire_process_lock()
        self.token = self.registry.token()
        self.engine = None
        self.state = self.registry
        self.host, self.port, self.server = "127.0.0.1", port, None
        self._setup_lock = threading.Lock()
        self._picker_lock = threading.Lock()
        self._request_lock = threading.Lock()
        self._closing = False

    def configure(self, payload):
        with self._setup_lock:
            if self.engine is not None:
                raise MigrationError("A migration is already configured. Restart the helper to change scope.")
            allowed = {"target", "target_home", "workspace_roots", "identity_file", "apply"}
            if not isinstance(payload, dict) or set(payload) - allowed:
                raise MigrationError("Unexpected setup fields")
            if not isinstance(payload.get("apply", False), bool):
                raise MigrationError("Enable changes must be true or false")
            roots = payload.get("workspace_roots", [])
            if not isinstance(roots, list) or len(roots) > 100 or not all(isinstance(x, str) for x in roots):
                raise MigrationError("Select at most 100 workspace roots")
            for field in ("target", "target_home", "identity_file"):
                if not isinstance(payload.get(field, ""), str):
                    raise MigrationError("Invalid setup text field")
            config = MigrationConfig(
                target=payload.get("target", ""), target_home=payload.get("target_home", ""),
                source_home=self.source_home, workspace_roots=roots,
                state_dir=str(self.registry.root / "validation"),
                apply=payload.get("apply", False),
                ssh=SSHOptions(identity_file=payload.get("identity_file") or None),
            ).validate()
            saved = {"target": config.target, "target_home": config.target_home,
                     "workspace_roots": sorted(config.workspace_roots)}
            key = hashlib.sha256(json.dumps(saved, sort_keys=True).encode()).hexdigest()
            from dataclasses import replace
            config = replace(config, workspace_roots=saved["workspace_roots"],
                             state_dir=str(self.registry.root / "migrations" / key)).validate()
            state = StateStore(config.state_dir)
            state.acquire_process_lock()
            try:
                engine = MigrationEngine(config, state)
                engine.reconcile_startup()
                self.registry.update(saved=saved)
            except BaseException:
                state.release_process_lock()
                raise
            self.state, self.engine = state, engine

    def can_shutdown(self):
        if not self._request_lock.acquire(blocking=False):
            return False
        try:
            allowed = self.engine is None or (
                self.state.read().get("status") not in ("running", "paused")
                and not (self.engine._thread and self.engine._thread.is_alive()))
            if allowed:
                self._closing = True
            return allowed
        finally:
            self._request_lock.release()

    def close(self):
        if self.engine is not None:
            self.engine.shutdown()
            self.state.release_process_lock()
        self.registry.release_process_lock()

    def choose_folders(self):
        if platform.system() != "Darwin":
            raise MigrationError("Native folder selection requires macOS")
        if not self._picker_lock.acquire(blocking=False):
            raise MigrationError("A folder picker is already open")
        try:
            # Fixed script only. No browser input is interpolated into code.
            result = subprocess.run(["/usr/bin/osascript", "-l", "JavaScript", "-e", '''
const app = Application.currentApplication();
app.includeStandardAdditions = true;
JSON.stringify(app.chooseFolder({withPrompt: "Choose workspace folders for Codex Migrate",
                                multipleSelectionsAllowed: true}).map(String));
'''], capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                if "(-128)" in result.stderr:
                    return []
                raise MigrationError("Folder picker could not open. Enter folder paths or allow the macOS permission prompt.")
            paths = json.loads(result.stdout)
            if not isinstance(paths, list) or not all(isinstance(x, str) and "\n" not in x and "\r" not in x for x in paths):
                raise MigrationError("Folder names containing line breaks are not supported")
            return paths
        finally:
            self._picker_lock.release()

    def _handler(self):
        setup = self
        base = super()._handler()

        class Handler(base):
            def setup(self):
                super().setup()
                self.connection.settimeout(10)

            def _local(self):
                expected = "127.0.0.1:%d" % self.server.server_port
                origin = self.headers.get("Origin")
                return self.headers.get("Host") == expected and origin in (None, "http://" + expected)

            def do_GET(self):
                if not self._local():
                    self._json(403, {"error": "Local origin required"})
                    return
                if self.path == "/api/setup":
                    if not self._authorized():
                        self._json(403, {"error": "Missing or invalid local control token"})
                        return
                    self._json(200, {"saved": setup.registry.read().get("saved"),
                                     "attached": setup.engine is not None})
                    return
                if self.path == "/":
                    self._html(SETUP_HTML)
                    return
                if self.path == "/migration" and setup.engine is not None:
                    self.path = "/"
                elif setup.engine is None:
                    self._json(409, {"error": "Configure a migration first"})
                    return
                super().do_GET()

            def do_POST(self):
                with setup._request_lock:
                    if setup._closing:
                        self._json(409, {"error": "The helper is closing. Reopen it to continue."})
                        return
                    self._post()

            def _post(self):
                if not self._local() or not self._authorized():
                    self._json(403, {"error": "Local origin and control token required"})
                    return
                if self.path in ("/api/setup", "/api/folders", "/api/suggestions"):
                    try:
                        length = int(self.headers.get("Content-Length", "0"))
                        if not 0 < length <= 32768:
                            raise MigrationError("Invalid request size")
                        payload = json.loads(self.rfile.read(length))
                        if self.path == "/api/setup":
                            setup.configure(payload)
                            self._json(200, {"configured": True})
                        else:
                            if setup.engine is not None:
                                raise MigrationError("Folder selection is closed after configuration")
                            if payload != {}:
                                raise MigrationError("Folder selection accepts no arguments")
                            paths = setup.choose_folders() if self.path == "/api/folders" else [
                                str(Path(setup.source_home) / name) for name in ("Git", "Projects", "Developer")
                                if (Path(setup.source_home) / name).is_dir()]
                            self._json(200, {"paths": paths, "message": "Review the selected folders. Suggestions are not an exhaustive repository scan."})
                    except Exception:
                        # Do not return user-supplied key paths or exception reprs.
                        self._json(400, {"error": "Setup failed. Check the destination, absolute folder paths, permissions, and whether another migration or folder picker is already open."})
                    return
                if setup.engine is None:
                    self._json(409, {"error": "Configure a migration first"})
                    return
                super().do_POST()

        return Handler
