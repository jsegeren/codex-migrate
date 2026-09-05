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
from codex_migrate.component_migration import ComponentMigrationEngine
from codex_migrate.state import StateStore
from codex_migrate.support import with_support, SUPPORT_HTML


SETUP_HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="data:,"><title>Set up your migration — Codex Migrate</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#080b10;color:#f7f8fa;font:500 17px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;overflow-wrap:anywhere}
main{width:min(800px,calc(100% - 32px));margin:40px auto}h1{font-size:clamp(32px,6vw,48px);line-height:1.1}h2{font-size:24px}p{color:#cbd2df}section,fieldset{background:#111722;border:1px solid #465268;border-radius:16px;padding:24px;margin:24px 0;min-width:0}
label{display:block;margin:16px 0 6px}input,textarea,button,select{font:inherit}input:not([type=checkbox]),textarea,select{display:block;width:100%;padding:12px;border:1px solid #8996ad;border-radius:8px;color:#f7f8fa;background:#080b10}textarea{min-height:120px}button,a.button{display:inline-block;padding:12px 18px;border:1px solid #a08bd3;border-radius:9px;background:#6042a6;color:white;font-weight:700;cursor:pointer;text-decoration:none;max-width:100%;white-space:normal}button:disabled{opacity:.6;cursor:wait}.controls{display:flex;gap:12px;flex-wrap:wrap}.check{display:flex;gap:12px;align-items:flex-start}.check input{width:22px;height:22px;flex:none;margin-top:4px}a{color:#d9cdff}:focus-visible{outline:3px solid #d9cdff;outline-offset:4px}#error{color:#ffc3c8}#message{color:#cbd2df}footer{font-size:15px;color:#cbd2df}legend{font-weight:700;font-size:24px}[hidden]{display:none!important}@media(max-width:480px){section,fieldset{padding:16px}main{margin:24px auto}}
.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}.setup-step h2{margin-top:0}button.secondary{background:transparent;border-color:#8996ad}#step-progress{color:#d9cdff;font-weight:700}#review dt{font-size:15px;color:#cbd2df}#review dd{margin:0 0 16px;font-weight:700}details{margin:18px 0}summary{cursor:pointer;font-weight:650}#message:empty{display:none}
</style></head><body><main>
<a class="support-link" href="#migration-help">Help / Email support</a>
<h1>Let’s move your Codex.</h1><p>Your conversations, skills, and unfinished work. Directly from this Mac to your new one.</p>
<div id="error" role="alert"></div><p id="message" role="status" aria-live="polite">Connecting to your local helper…</p>
<section id="attached" hidden><h2>Your migration is configured</h2><p>Continue to its status, backup checks, pause/resume controls and recovery guidance. Keep the same destination and scope when resuming. Changing scope while staged data exists requires reviewing that migration’s recovery instructions; restarting alone does not adopt it.</p><a class="button" id="continue" href="/migration">Open migration dashboard</a></section>
<p id="step-progress" aria-live="polite">Step 1 of 3 · Your new Mac</p>
<form id="setup" novalidate><fieldset id="fields" disabled><legend class="sr-only">Migration setup</legend>
<div id="step-1" class="setup-step"><h2 tabindex="-1">Your new Mac</h2>
<p>Connect both Macs to Wi-Fi, or use a compatible USB-C/Thunderbolt connection.</p>
<label for="computer">New Mac’s name or address</label><input id="computer" autocomplete="off" placeholder="e.g. Joshuas-MacBook-Pro.local" required>
<label for="username">Your username on the new Mac</label><input id="username" autocomplete="off" placeholder="e.g. joshua" required>
<input id="target" type="hidden">
<details><summary>Help finding and connecting your Mac</summary><p>On the new Mac, open System Settings → General → Sharing → Remote Login. Turn it on for your account; the login address shown there contains your username and Mac’s address. Install Codex there and sign in once.</p>
<p>The current build needs SSH key login set up between the Macs. Connect once in Terminal using <code>ssh new-user@new-mac.local</code> and verify the host fingerprint. An interactive password prompt is not supported yet. A charging-only cable cannot carry the transfer.</p></details>
<details><summary>Advanced connection settings</summary>
<label for="target-home">New Mac’s home folder</label><input id="target-home" autocomplete="off" placeholder="/Users/username" required>
<label for="identity">Existing SSH key path (optional)</label><input id="identity" autocomplete="off" spellcheck="false" aria-describedby="key-help"><p id="key-help">Leave empty to use your SSH configuration. Selecting a key does not add it to the migration, and this selection is not saved. A key stored inside a selected workspace is copied with that workspace.</p></details>
<div class="controls"><button type="button" id="next-1">Continue</button></div></div>
<div id="step-2" class="setup-step" hidden><h2 tabindex="-1">What would you like to move?</h2>
<label for="mode">What do you want to move?</label><select id="mode"><option value="full">Full Codex migration and selected workspaces</option><option value="skills">Custom skills only</option></select>
<fieldset id="skill-components" hidden><legend>Skills to include</legend><label class="check"><input type="checkbox" id="personal-skills" checked><span>Personal custom skills (.agents/skills and legacy .codex/skills)</span></label><label class="check"><input type="checkbox" id="workspace-skills"><span>Workspace skills inside the project folders selected below</span></label><p>Skills only: conversations, configuration and whole repositories are not copied. Other destination skills are kept. Inspect the list, stage it, then confirm Finalize separately.</p></fieldset>
<p id="folder-summary" aria-live="polite">No project folders selected.</p>
<div class="controls"><button type="button" id="folders">Choose folders on this Mac…</button><button type="button" id="suggest" class="secondary">Suggest common folders</button></div>
<details><summary>Review or edit folder paths</summary><label for="workspaces" id="workspace-label">Workspace folders on this Mac, one per line</label><textarea id="workspaces" spellcheck="false" aria-describedby="scope-help"></textarea></details>
<p id="scope-help">Selected folders include unfinished work and any secrets stored inside them. Full migration includes Codex state and personal skills; other folders are not automatically included.</p>
<div class="controls"><button type="button" class="secondary" id="back-2">Back</button><button type="button" id="next-2">Review migration</button></div></div>
<div id="step-3" class="setup-step" hidden><h2 tabindex="-1">Ready to check both Macs</h2>
<dl id="review"></dl><p>We’ll check the connection and available space before you start. A verified backup is required before replacing destination data.</p>
<p id="replacement-note">This replaces selected destination data; it does not merge separate work. Keep your old Mac intact.</p>
<details><summary>What gets saved between runs?</summary><p>Your destination and folder selection are saved privately on this Mac. Changes reset to disabled on each launch; SSH key selections are not saved.</p></details>
<label class="check"><input id="apply" type="checkbox"><span>Allow this migration to copy files to my new Mac. I’ll review the checks before starting.</span></label>
<div class="controls"><button type="button" class="secondary" id="back-3">Back</button><button type="submit" id="open">Continue to migration</button></div>
</div></fieldset></form>
<details><summary>Resuming a migration or only restoring skills?</summary><p>For migrations started in this browser setup, reopen the helper after interruption, review the restored setup, enable changes if appropriate, and use Resume in the dashboard. Staged data and backup receipts remain on your Macs. Never delete them just because a progress bar reaches 100%.</p><p>Already started with the CLI or native setup? Resume using that same entry point and configuration. This browser setup does not import those older migration records, and it will not adopt or overwrite their staging.</p><p>Choose Custom skills only above for a smaller repair. It has its own saved staging, pause/resume controls and verified destination backups; a full migration’s staging is left alone.</p></details>
<footer>Codex Migrate is independent software. Not affiliated with or endorsed by OpenAI. Mac-to-Mac only.</footer>
</main><script>
const $=id=>document.getElementById(id);
const storageKey="codex-migrate-token:"+location.origin;
const incoming=new URLSearchParams(location.hash.slice(1)).get("token");
if(incoming)sessionStorage.setItem(storageKey,incoming);
const token=incoming||sessionStorage.getItem(storageKey)||"";
history.replaceState(null,"",location.pathname);
const roots=()=>$("workspaces").value.split("\n").map(x=>x.trim()).filter(Boolean);
const fullScopeHelp=$("scope-help").textContent;
const fullKeyHelp=$("key-help").textContent;
let step=1;
function syncDestination(){const user=$("username").value.trim();const host=$("computer").value.trim();$("target").value=user+"@"+host;if(!$("target-home").dataset.custom)$("target-home").value=user?"/Users/"+user:"";}
$("username").oninput=syncDestination;$("computer").oninput=syncDestination;$("target-home").oninput=()=>{$("target-home").dataset.custom="true"};
function folderSummary(){$("folder-summary").textContent=roots().length?roots().length+" project folder"+(roots().length===1?"":"s")+" selected.":"No project folders selected.";}
$("workspaces").oninput=folderSummary;
function showStep(next){step=next;for(let n=1;n<=3;n++)$("step-"+n).hidden=n!==step;$("step-progress").textContent="Step "+step+" of 3 · "+["Your new Mac","What to move","Review"][step-1];$("step-"+step).querySelector("h2").focus();}
function connectionValid(){syncDestination();for(const id of ["computer","username","target-home"]){if(!$(id).checkValidity()){showStep(1);$(id).closest("details")?.setAttribute("open","");$(id).reportValidity();return false}}return true;}
$("next-1").onclick=()=>{if(connectionValid())showStep(2)};$("back-2").onclick=()=>showStep(1);$("back-3").onclick=()=>showStep(2);
$("next-2").onclick=()=>{const skills=$("mode").value==="skills";$("review").replaceChildren();for(const [label,value] of [["New Mac",$("target").value],["Moving",skills?"Selected custom skills":"Codex conversations, settings and skills"],["Project folders",String(roots().length)]]){const dt=document.createElement("dt"),dd=document.createElement("dd");dt.textContent=label;dd.textContent=value;$("review").append(dt,dd)}$("replacement-note").textContent=skills?"Matching destination skills are backed up and replaced. Other skills, conversations and projects are kept.":"This replaces selected destination data; it does not merge separate work. Keep your old Mac intact.";showStep(3)};
function modeChanged(){const skills=$("mode").value==="skills";$("key-help").textContent=skills?"Selecting an SSH key does not add it to the migration, and the selection is not saved. Only selected skill contents are copied; review them for private files. Protected SSH and Codex login files are rejected.":fullKeyHelp;$("skill-components").hidden=!skills;$("workspace-label").textContent=skills?"Project folders to search for workspace skills, one per line":"Workspace folders on this Mac, one per line";$("scope-help").textContent=skills?"These folders are searched only when Workspace skills is checked. Only discovered .agents/skills directories are copied, not the whole project. Personal skills need no project-folder selection. Skill contents can include private files; review the discovered list before transfer.":fullScopeHelp;}
$("mode").onchange=modeChanged;
async function api(path,body){const r=await fetch(path,{method:body?"POST":"GET",headers:{"X-Codex-Migrate-Token":token,"Content-Type":"application/json"},...(body?{body:JSON.stringify(body)}:{})});const result=await r.json();if(!r.ok)throw Error(result.error||"The request failed");return result}
function attached(){ $("attached").hidden=false;$("setup").hidden=true;$("step-progress").hidden=true;$("continue").href="/migration#token="+encodeURIComponent(token);$("message").textContent="The helper is ready. No transfer was started automatically."; }
async function load(){try{const s=await api("/api/setup");if(s.attached){attached();return}const c=s.saved||{};$("target").value=c.target||"";const split=(c.target||"").lastIndexOf("@");$("username").value=split>=0?c.target.slice(0,split):"";$("computer").value=split>=0?c.target.slice(split+1):"";$("target-home").value=c.target_home||"";if(c.target_home&&c.target_home!=="/Users/"+$("username").value)$("target-home").dataset.custom="true";else delete $("target-home").dataset.custom;$("workspaces").value=(c.workspace_roots||[]).join("\n");$("mode").value=c.mode||"full";$("personal-skills").checked=!c.components||c.components.includes("personal-skills");$("workspace-skills").checked=(c.components||[]).includes("workspace-skills");modeChanged();folderSummary();$("apply").checked=false;$("fields").disabled=false;$("message").textContent=s.saved?"Restored your last setup. Review it before continuing; changes remain disabled.":""}catch(e){$("error").textContent=e.message+". Reopen the browser from the local helper if its token is missing."}}
async function folders(path){$("folders").disabled=true;$("suggest").disabled=true;try{const r=await api(path,{});$("workspaces").value=[...new Set([...roots(),...r.paths])].join("\n");folderSummary();$("message").textContent=r.message}catch(e){$("error").textContent=e.message}finally{$("folders").disabled=false;$("suggest").disabled=false}}
$("folders").onclick=()=>folders("/api/folders");$("suggest").onclick=()=>folders("/api/suggestions");
$("setup").onsubmit=async e=>{e.preventDefault();if(step<3){$(step===1?"next-1":"next-2").click();return}if(!connectionValid())return;$("open").disabled=true;$("error").textContent="";try{await api("/api/setup",{target:$("target").value.trim(),target_home:$("target-home").value.trim(),workspace_roots:roots(),identity_file:$("identity").value.trim(),apply:$("apply").checked,mode:$("mode").value,components:$("mode").value==="skills"?["personal-skills","workspace-skills"].filter(id=>$(id).checked):[]});location.href="/migration#token="+encodeURIComponent(token)}catch(e){$("error").textContent=e.message;$("open").disabled=false}};
load();
</script></body></html>'''
SETUP_HTML = with_support(SETUP_HTML)
SETUP_HTML = SETUP_HTML.replace(SUPPORT_HTML, '<details id="setup-help"><summary>Help and diagnostic report</summary>' + SUPPORT_HTML + '</details>')
SETUP_HTML = SETUP_HTML.replace('href="#migration-help"', 'href="#setup-help"')
SETUP_HTML = SETUP_HTML.replace('</body>', '''<script>
document.querySelector('.support-link').addEventListener('click',()=>{
  document.getElementById('setup-help').open=true;
});
</script></body>''')


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
            allowed = {"target", "target_home", "workspace_roots", "identity_file", "apply", "mode", "components"}
            if not isinstance(payload, dict) or set(payload) - allowed:
                raise MigrationError("Unexpected setup fields")
            if not isinstance(payload.get("apply", False), bool):
                raise MigrationError("Enable changes must be true or false")
            mode = payload.get("mode", "full")
            if mode not in ("full", "skills"):
                raise MigrationError("Choose full migration or skills only")
            components = payload.get("components", [])
            if not isinstance(components, list) or not all(isinstance(x, str) for x in components):
                raise MigrationError("Invalid skills selection")
            if mode == "full" and components:
                raise MigrationError("Component choices apply only to skills-only migration")
            if mode == "skills" and (not components or set(components) - {"personal-skills", "workspace-skills"}):
                raise MigrationError("Choose personal skills, workspace skills, or both")
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
            if mode == "skills":
                saved.update(mode="skills", components=sorted(set(components)))
            key = hashlib.sha256(json.dumps(saved, sort_keys=True).encode()).hexdigest()
            from dataclasses import replace
            config = replace(config, workspace_roots=saved["workspace_roots"],
                             state_dir=str(self.registry.root / "migrations" / key)).validate()
            state = StateStore(config.state_dir)
            state.acquire_process_lock()
            try:
                engine = (ComponentMigrationEngine(config, state, components)
                          if mode == "skills" else MigrationEngine(config, state))
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
            allowed = self._idle_for_shutdown()
            if allowed:
                self._closing = True
            return allowed
        finally:
            self._request_lock.release()

    def _idle_for_shutdown(self):
        return self.engine is None or (
            self.state.read().get("status") not in ("running", "paused")
            and not (self.engine._thread and self.engine._thread.is_alive()))

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
                if self.path == "/api/support-report":
                    super().do_GET()
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
                if self.path == "/api/shutdown":
                    # _request_lock excludes concurrent configuration, pickers,
                    # and new operations while shutdown closes the action gate.
                    if not setup._idle_for_shutdown():
                        self._json(409, {"error": "Use Stop safely in the migration page, or wait for verification to finish, before quitting."})
                        return
                    setup._closing = True
                    self._json(200, {"closing": True})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
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
