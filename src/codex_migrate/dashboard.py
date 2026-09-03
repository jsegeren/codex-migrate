"""Loopback-only progress dashboard with token-protected controls."""

from __future__ import annotations

import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import signal
import threading
from typing import Any, Dict, Optional
import webbrowser

from codex_migrate.migration import MigrationEngine, MigrationError
from codex_migrate.security import redact
from codex_migrate.state import StateStore


HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <link rel="icon" href="data:,">
  <title>Codex Migrate</title>
  <style>
    :root { color-scheme: dark; --bg:#080b10; --panel:#111722; --line:#273145; --text:#f7f8fa; --muted:#b9c3d2; --blue:#5b8cff; --action:#245bd7; --green:#40d18a; --amber:#ffbd59; --red:#ff6b75; }
    * { box-sizing:border-box; }
    body { margin:0; min-height:100vh; background:radial-gradient(circle at 20% 0,#172038 0,transparent 36%),var(--bg); color:var(--text); font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
    main { width:min(920px,calc(100% - 32px)); margin:48px auto; }
    header { display:flex; justify-content:space-between; gap:24px; align-items:flex-start; margin-bottom:24px; }
    h1 { margin:0; font-size:clamp(30px,6vw,54px); letter-spacing:-.045em; line-height:1; }
    .tag { border:1px solid var(--line); border-radius:999px; padding:7px 11px; color:var(--muted); white-space:nowrap; }
    .lede { color:var(--muted); font-size:17px; max-width:650px; margin:14px 0 0; }
    .panel { background:color-mix(in srgb,var(--panel) 94%,transparent); border:1px solid var(--line); border-radius:20px; padding:24px; box-shadow:0 24px 80px #0007; }
    .status-row { display:flex; align-items:center; justify-content:space-between; gap:20px; }
    .eyebrow { text-transform:uppercase; letter-spacing:.12em; font-size:14px; color:var(--muted); }
    #status { font-size:28px; font-weight:700; margin-top:4px; }
    #percent { font-size:36px; font-variant-numeric:tabular-nums; font-weight:750; }
    .track { height:13px; border-radius:999px; overflow:hidden; background:#20293a; margin:20px 0 14px; }
    #bar { height:100%; width:0; background:linear-gradient(90deg,var(--blue),#8b78ff); transition:width .35s ease; }
    #message { min-height:24px; color:var(--muted); font-size:16px; }
    .grid { display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin:20px 0; }
    .metric { border:1px solid var(--line); border-radius:14px; padding:14px; min-width:0; }
    .metric strong { display:block; margin-top:4px; overflow-wrap:anywhere; }
    .controls { display:flex; flex-wrap:wrap; gap:10px; margin-top:22px; }
    .scope { margin-top:18px; border-top:1px solid var(--line); padding-top:16px; color:var(--muted); }
    .scope p { margin:5px 0; overflow-wrap:anywhere; }
    .scope ul { margin:7px 0 0; padding-left:22px; }
    button { appearance:none; border:1px solid var(--line); background:#182134; color:var(--text); border-radius:11px; padding:11px 15px; font:700 15px/1 inherit; cursor:pointer; }
    button.primary { background:var(--action); border-color:var(--action); }
    button:disabled { opacity:.38; cursor:not-allowed; }
    #warning,#error { display:none; margin-top:16px; border-radius:12px; padding:13px 15px; }
    #warning { background:#3a2b0f; color:#ffdc9d; border:1px solid #73551e; }
    #error { background:#3a151a; color:#ffc3c8; border:1px solid #7b2e37; }
    details { margin-top:18px; color:var(--muted); }
    code { color:#dbe5ff; overflow-wrap:anywhere; }
    footer { margin:20px 4px; color:var(--muted); font-size:14px; }
    @media (max-width:680px) { main{margin:24px auto}.grid{grid-template-columns:1fr}.status-row{align-items:flex-end}.panel{padding:18px}header{display:block}.tag{display:inline-block;margin-top:16px} }
  </style>
</head>
<body>
<main>
  <header>
    <div><h1>Codex Migrate</h1><p class="lede">Move local Codex conversations, configuration, repositories, worktrees, and unfinished work to another Mac—with resumable staging and verification.</p></div>
    <span class="tag">Unofficial · local only</span>
  </header>
  <section class="panel">
    <div class="status-row"><div><div class="eyebrow" id="phase">Not started</div><div id="status">Ready</div></div><div id="percent">0%</div></div>
    <div class="track" role="progressbar" aria-label="Migration progress" aria-valuemin="0" aria-valuemax="100"><div id="bar"></div></div>
    <div id="message" role="status" aria-live="polite">Connecting to the local migration service…</div>
    <div class="grid">
      <div class="metric"><span class="eyebrow">Route</span><strong id="route">—</strong></div>
      <div class="metric"><span class="eyebrow">Staged</span><strong id="bytes">—</strong></div>
      <div class="metric"><span class="eyebrow">Current item</span><strong id="item">—</strong></div>
    </div>
    <div class="scope">
      <div class="eyebrow">Configured migration scope</div>
      <p><strong>Codex:</strong> <code id="codex-scope">—</code></p>
      <p><strong>SSH destination:</strong> <code id="ssh-target">—</code></p>
      <p><strong>Selected workspaces:</strong> <span id="workspace-count">0</span></p>
      <ul id="workspace-list"></ul>
    </div>
    <div class="controls">
      <button id="inspect" disabled>Inspect</button>
      <button class="primary" id="start" disabled>Start transfer</button>
      <button id="pause" disabled>Pause</button>
      <button id="resume" disabled>Resume</button>
      <button class="primary" id="finalize" disabled>Finalize</button>
      <button id="cancel" disabled>Stop safely</button>
    </div>
    <div id="warning"></div><div id="error" role="alert"></div>
    <details><summary>What is protected?</summary><p>The source is never modified. Destination Codex account authentication and installation identity are excluded from transfer and checked after installation. The destination receives a timestamped backup before replacement. Interrupted rsync staging is kept so Resume can continue.</p><p id="compat"></p></details>
  </section>
  <footer>Codex Migrate is an independent open-source project. It is not made by, affiliated with, or endorsed by OpenAI.</footer>
</main>
<script>
const token=new URLSearchParams(location.hash.slice(1)).get("token")||"";
history.replaceState(null,"",location.pathname);
const $=id=>document.getElementById(id);
let latestState={};
const fmt=n=>{if(!Number.isFinite(n))return "—";const u=["B","KB","MB","GB","TB"];let i=0;while(n>=1000&&i<u.length-1){n/=1000;i++}return `${n.toFixed(n>=100?0:n>=10?1:2)} ${u[i]}`};
async function api(path,options={}){const response=await fetch(path,{...options,headers:{"X-Codex-Migrate-Token":token,"Content-Type":"application/json",...(options.headers||{})}});const body=await response.json();if(!response.ok)throw new Error(body.error||`Request failed (${response.status})`);return body}
function render(s){latestState=s;const p=Math.max(0,Math.min(100,Number(s.percent)||0));$("percent").textContent=`${p.toFixed(p===100?0:1)}%`;$("bar").style.width=`${p}%`;$("bar").parentElement.setAttribute("aria-valuenow",String(p));$("phase").textContent=String(s.phase||"unknown").replaceAll("_"," ");$("status").textContent=String(s.status||"unknown").replaceAll("_"," ");$("message").textContent=s.message||"";$("route").textContent=s.route||"—";$("bytes").textContent=`${fmt(s.bytes_staged||0)} / ${fmt(s.bytes_total||0)}`;$("item").textContent=s.current_item||"—";$("warning").style.display=s.warning?"block":"none";$("warning").textContent=s.warning||"";$("error").style.display=s.error?"block":"none";$("error").textContent=s.error||"";$("compat").textContent=s.compatibility_command?`Different macOS usernames: after installation, run on the new Mac: ${s.compatibility_command}`:"";const c=s.config||{};$("codex-scope").textContent=`${c.source_home||"—"}/.codex → ${c.target_home||"—"}/.codex`;$("ssh-target").textContent=`${c.target||"—"} · ${c.target_home||"—"}`;const roots=Array.isArray(c.workspace_roots)?c.workspace_roots:[];$("workspace-count").textContent=String(roots.length);$("workspace-list").replaceChildren(...roots.map(root=>{const li=document.createElement("li");const prefix=`${c.source_home}/`;const relative=root.startsWith(prefix)?root.slice(prefix.length):root;li.textContent=`${root} → ${c.target_home}/${relative}`;return li}));const active=s.status==="running";const canStart=["idle","ready"].includes(s.status);const canFinalize=s.status==="ready_to_finalize"||(s.status==="waiting"&&["close_source_codex","close_target_codex"].includes(s.phase));$("inspect").disabled=active;$("start").disabled=!canStart||!s.apply;$("pause").disabled=!active||!["staging","final_delta"].includes(s.phase);$("resume").disabled=!s.apply||!['paused','cancelled','failed','interrupted'].includes(s.status);$("finalize").disabled=!canFinalize||!s.apply;$("cancel").disabled=!((active&&["inspecting","staging","final_delta"].includes(s.phase))||s.status==="paused");}
async function refresh(){try{render(await api("/api/status"))}catch(error){$("error").style.display="block";$("error").textContent=error.message}}
async function action(name){const c=latestState.config||{};if(name==="finalize"&&!confirm(`Back up, then replace ${c.target_home}/.codex and ${c.workspace_roots?.length||0} selected workspace root(s) on ${c.target}?`))return;try{render(await api("/api/action",{method:"POST",body:JSON.stringify({action:name,confirmed:name==="finalize"})}))}catch(error){$("error").style.display="block";$("error").textContent=error.message}}
for(const name of ["inspect","start","pause","resume","finalize","cancel"]){$(name).addEventListener("click",()=>action(name))}
refresh();setInterval(refresh,2500);
</script>
</body></html>"""


class Dashboard:
    def __init__(
        self,
        engine: MigrationEngine,
        state: StateStore,
        host: str = "127.0.0.1",
        port: int = 8765,
    ) -> None:
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise ValueError("the dashboard may bind only to loopback")
        self.engine = engine
        self.state = state
        self.host = host
        self.port = port
        self.token = state.token()
        self.server: Optional[ThreadingHTTPServer] = None
        self.state.acquire_process_lock()
        self.engine.reconcile_startup()

    def _handler(self):
        dashboard = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "CodexMigrate/0.1"

            def log_message(self, format: str, *args: Any) -> None:
                return

            def _authorized(self) -> bool:
                provided = self.headers.get("X-Codex-Migrate-Token", "")
                return hmac.compare_digest(provided, dashboard.token)

            def _json(self, status: int, body: Dict[str, Any]) -> None:
                encoded = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def do_GET(self) -> None:
                if self.path == "/" or self.path.startswith("/?"):
                    encoded = HTML.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.send_header("Referrer-Policy", "no-referrer")
                    self.send_header(
                        "Content-Security-Policy",
                        "default-src 'self'; connect-src 'self'; img-src 'self' data:; "
                        "style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                        "frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
                    )
                    self.send_header("Content-Length", str(len(encoded)))
                    self.end_headers()
                    self.wfile.write(encoded)
                    return
                if self.path == "/api/status":
                    if not self._authorized():
                        self._json(403, {"error": "Missing or invalid local control token"})
                        return
                    body = dashboard.state.read()
                    body["apply"] = dashboard.engine.config.apply
                    body["config"] = dashboard.engine.config.to_public_dict()
                    body["compatibility_command"] = dashboard.engine.compatibility_command()
                    self._json(200, body)
                    return
                self._json(404, {"error": "Not found"})

            def do_POST(self) -> None:
                if self.path != "/api/action":
                    self._json(404, {"error": "Not found"})
                    return
                if not self._authorized():
                    self._json(403, {"error": "Missing or invalid local control token"})
                    return
                try:
                    declared_length = int(self.headers.get("Content-Length", "0"))
                    if declared_length < 0 or declared_length > 4096:
                        raise MigrationError("Invalid request size")
                    length = declared_length
                    payload = json.loads(self.rfile.read(length) or b"{}")
                    action = payload.get("action")
                    if action == "inspect":
                        if dashboard.state.read().get("status") == "running":
                            raise MigrationError("Wait for the current migration action to finish")
                        dashboard.engine.preflight()
                    elif action == "start":
                        dashboard.engine.start_preseed()
                    elif action == "pause":
                        dashboard.engine.pause()
                    elif action == "resume":
                        dashboard.engine.resume()
                    elif action == "cancel":
                        dashboard.engine.cancel()
                    elif action == "finalize":
                        if payload.get("confirmed") is not True:
                            raise MigrationError("Finalization requires explicit confirmation")
                        dashboard.engine.start_finalize()
                    else:
                        raise MigrationError("Unknown action")
                    body = dashboard.state.read()
                    body["apply"] = dashboard.engine.config.apply
                    body["config"] = dashboard.engine.config.to_public_dict()
                    body["compatibility_command"] = dashboard.engine.compatibility_command()
                    self._json(202, body)
                except Exception as error:
                    protected = [
                        dashboard.engine.config.ssh.identity_file or "",
                        dashboard.engine.config.ssh.known_hosts_file or "",
                    ]
                    self._json(400, {"error": redact(str(error), protected)})

        return Handler

    def serve(self, open_browser: bool = True) -> None:
        previous_handlers = {}

        def interrupt_for_shutdown(_signum, _frame):
            raise KeyboardInterrupt

        if threading.current_thread() is threading.main_thread():
            for name in ("SIGTERM", "SIGHUP"):
                if hasattr(signal, name):
                    value = getattr(signal, name)
                    previous_handlers[value] = signal.getsignal(value)
                    signal.signal(value, interrupt_for_shutdown)
        try:
            self.server = ThreadingHTTPServer((self.host, self.port), self._handler())
            url = "http://%s:%d/#token=%s" % (self.host, self.port, self.token)
            print("Codex Migrate dashboard: %s" % url)
            if open_browser:
                threading.Timer(0.3, lambda: webbrowser.open(url)).start()
            self.server.serve_forever()
        finally:
            for value, handler in previous_handlers.items():
                signal.signal(value, handler)
            if self.server:
                self.server.server_close()
            self.close()

    def close(self) -> None:
        self.engine.shutdown()
        self.state.release_process_lock()
