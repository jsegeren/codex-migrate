"""Loopback-only progress dashboard with token-protected controls."""

from __future__ import annotations

import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import signal
from socketserver import TCPServer
import threading
from typing import Any, Dict, Optional
import webbrowser

from codex_migrate.migration import MigrationEngine, MigrationError
from codex_migrate.security import redact
from codex_migrate.state import StateStore, public_state
from codex_migrate.support import diagnostic_report, with_support


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
    header { display:flex; justify-content:space-between; gap:24px; align-items:flex-start; margin-bottom:32px; }
    header > div { min-width:0; }
    header > .support-link { flex:none; background:transparent; border-color:#8996ad; color:#d9cdff; }
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
    #message { min-height:24px; color:var(--muted); font-size:16px; overflow-wrap:anywhere; }
    .grid { display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin:20px 0; }
    .metric { border:1px solid var(--line); border-radius:14px; padding:14px; min-width:0; }
    .metric strong { display:block; margin-top:4px; overflow-wrap:anywhere; }
    .controls { display:flex; flex-wrap:wrap; gap:10px; margin-top:22px; }
    .scope { margin-top:18px; border-top:1px solid var(--line); padding-top:16px; color:var(--muted); }
    .scope p { margin:5px 0; overflow-wrap:anywhere; }
    .scope ul { margin:7px 0 0; padding-left:22px; }
    .scope li { overflow-wrap:anywhere; }
    #backup-safety { margin-top:18px; padding:16px; border:1px solid var(--line); border-radius:12px; }
    #backup-safety p { margin:6px 0; overflow-wrap:anywhere; }
    #backup-safety.blocked { border:2px solid var(--red); background:#3a151a; }
    #recovery-message:focus,#path-message:focus,#git-check-message:focus { outline:3px solid #d9cdff; outline-offset:4px; }
    #path-next[hidden] { display:none; }
    #recovery-items { padding-left:20px; }
    #recovery-items li { overflow-wrap:anywhere; }
    button { appearance:none; border:1px solid var(--line); background:#182134; color:var(--text); border-radius:11px; padding:11px 15px; font-family:inherit; font-size:15px; font-weight:700; line-height:1; cursor:pointer; }
    button.primary { background:var(--action); border-color:var(--action); }
    button:disabled { opacity:.38; cursor:not-allowed; }
    #warning,#error { display:none; margin-top:16px; border-radius:12px; padding:13px 15px; overflow-wrap:anywhere; }
    #warning { background:#3a2b0f; color:#ffdc9d; border:1px solid #73551e; }
    #error { background:#3a151a; color:#ffc3c8; border:1px solid #7b2e37; }
    details { margin-top:18px; color:var(--muted); }
    code { color:#dbe5ff; overflow-wrap:anywhere; }
    #path-command pre { white-space:pre-wrap; overflow-wrap:anywhere; font-size:15px; }
    footer { margin:20px 4px; color:var(--muted); font-size:14px; }
    @media (max-width:680px) { main{margin:24px auto}.grid{grid-template-columns:1fr}.status-row{align-items:flex-end}.panel{padding:18px}header{flex-direction:column;gap:24px}.tag{display:inline-block;margin-top:16px} }
  </style>
</head>
<body>
<main>
  <header>
    <div><h1>Codex Migrate</h1><p class="lede">Move local Codex conversations, configuration, repositories, worktrees, and unfinished work to another Mac—with resumable staging and verification.</p></div>
    <a class="support-link" href="#migration-help">Help / Email support</a>
  </header>
  <section class="panel">
    <div class="status-row"><div><div class="eyebrow" id="phase">Not started</div><div id="status">Ready</div></div><div id="percent">0%</div></div>
    <div class="track" role="progressbar" aria-label="Migration progress" aria-valuemin="0" aria-valuemax="100"><div id="bar"></div></div>
    <div id="message" role="status" aria-live="polite">Connecting to the local migration service…</div>
    <div class="grid">
      <div class="metric"><span class="eyebrow">Route</span><strong id="route">—</strong></div>
      <div class="metric"><span class="eyebrow" id="size-heading">Staged / estimated total</span><strong id="bytes">—</strong></div>
      <div class="metric"><span class="eyebrow">Current item</span><strong id="item">—</strong></div>
    </div>
    <div class="scope">
      <div class="eyebrow">Configured migration scope</div>
      <p><strong>Codex:</strong> <code id="codex-scope">—</code></p>
      <p><strong>SSH destination:</strong> <code id="ssh-target">—</code></p>
      <p><strong id="workspace-heading">Selected workspaces:</strong> <span id="workspace-count">0</span></p>
      <details><summary>Selected folders</summary><ul id="workspace-list"></ul></details>
      <p><strong id="skill-heading">Personal skills:</strong> <span id="skill-count">Not inspected yet</span></p>
      <details><summary>Skills included</summary><p id="skill-explanation">Custom skills are included from .agents/skills and legacy .codex/skills, with the current location taking precedence. Other destination skills are kept.</p><ul id="skill-list"></ul></details>
    </div>
    <details id="git-scope" class="scope"><summary>Git repositories, worktrees and required folders</summary>
      <p id="git-summary">Git scope has not been inspected with this version.</p>
      <p id="workspace-proof">Workspace content verification is pending.</p>
      <p>Dependency inspection searches selected workspace folders and Codex’s worktrees folder, then checks linked Git storage. It does not test whether Git commands work on the destination. Workspace directory links are not searched for additional repositories. Other home folders are not searched.</p>
      <ul id="git-list"></ul><ul id="git-required"></ul><ul id="git-issues"></ul>
    </details>
    <details id="git-check-help" hidden><summary>Git verification</summary>
      <p id="git-check-message" role="status" tabindex="-1">Git checks run after installation and home-path verification.</p>
      <div class="controls"><button id="check_git" disabled>Check Git</button><button id="stop_git" disabled>Stop Git check</button></div>
      <details><summary>What this check means</summary><p>Compares discovered repositories with the saved source baseline: local object checks, HEAD, refs, index and status. It never copies, restores, fetches objects or runs repository helpers. Keep writing apps closed for a stable comparison.</p><p>Changes after installation may be your new work, not damage. Source issues, unavailable Git, filtered files and unsupported layouts can require review. Shallow history is not full remote history. Future hooks, remotes and development commands are not tested. Keep the backup and old Mac until you validate your work.</p></details>
    </details>
    <section id="backup-safety" aria-label="Backup protection" aria-live="polite">
      <strong id="backup-heading">Backup required before replacement</strong>
      <p id="backup-space">Destination space has not been checked yet.</p>
      <p id="backup-location">No verified backup recorded for this migration.</p>
      <p>Keep the old Mac intact. Close apps writing to selected folders before finalizing.</p>
      <details><summary>Backup and verification details</summary><p>Installation is blocked if space is insufficient or backup verification fails. There is no skip-backup option. Same-disk backups protect against replacement mistakes, not disk failure.</p><p id="codex-state-proof">Retained Codex state verification is pending.</p></details>
      <details id="recovery-help"><summary>Recover an interrupted installation</summary>
        <p>Check the destination before trying again. This reads saved recovery evidence and backup contents; it does not restore or remove files.</p>
        <div class="controls"><button id="check_recovery" disabled>Check recovery</button><button id="stop_recovery" disabled>Stop check</button><button id="restore_recovery" disabled>Restore backup</button></div>
        <p id="recovery-message" role="status" aria-live="polite" tabindex="-1">No recovery check has run.</p>
        <details id="recovery-details" hidden><summary>Last check details</summary><p id="recovery-time"></p><p id="recovery-backup"></p><p id="recovery-terminal"></p><ul id="recovery-items"></ul></details>
        <p>Restore keeps displaced current files separately. It returns the previous destination, not a completed migration. Keep the old Mac, staging, and backups intact.</p>
      </details>
    </section>
    <div class="controls">
      <button id="inspect" disabled>Inspect</button>
      <button class="primary" id="start" disabled>Start transfer</button>
      <button id="pause" disabled>Pause</button>
      <button id="resume" disabled>Resume</button>
      <button class="primary" id="finalize" disabled>Finalize</button>
      <button id="cancel" disabled>Stop safely</button>
    </div>
    <div id="warning"></div><div id="error" role="alert"></div>
    <a id="path-next" class="support-link" href="#path-help" hidden>Review home-path setup</a>
    <details id="path-help"><summary>Home-path compatibility</summary>
      <p id="path-message" role="status" tabindex="-1">Home paths have not been checked.</p>
      <button id="check_paths" disabled>Check home paths</button>
      <details id="path-command" hidden><summary>Fix a missing old home path</summary>
        <p>Run this command in Terminal on the new Mac only. It requires an administrator password, rechecks local accounts, and creates one home-directory link. It never replaces an existing entry. Then choose Check home paths.</p>
        <button id="copy-path-command">Copy command</button><pre><code id="compat"></code></pre>
        <p>A matching link is not proof that every chat or Git repository works. Keep the old Mac until you validate your work.</p>
      </details>
    </details>
    <details><summary>What is protected?</summary><p id="protection-explanation">The source is never modified. Destination Codex account authentication and installation identity are excluded from transfer and checked after installation. The destination receives a timestamped backup before replacement. Interrupted rsync staging is kept so Resume can continue.</p></details>
  </section>
  <details class="scope"><summary>Recent migration events</summary><p>Up to 60 phase, status, and failure-category changes. Times are UTC. This is not raw command output.</p><ol id="migration-events"><li>No events recorded yet.</li></ol></details>
  <footer>Codex Migrate is an independent open-source project. It is not made by, affiliated with, or endorsed by OpenAI.</footer>
</main>
<script>
const tokenKey="codex-migrate-token:"+location.origin;
const incomingToken=new URLSearchParams(location.hash.slice(1)).get("token");
if(incomingToken)sessionStorage.setItem(tokenKey,incomingToken);
const token=incomingToken||sessionStorage.getItem(tokenKey)||"";
history.replaceState(null,"",location.pathname);
const $=id=>document.getElementById(id);
let latestState={};
let recoveryWasChecking=false;
const fmt=n=>{if(!Number.isFinite(n))return "—";const u=["B","KB","MB","GB","TB"];let i=0;while(n>=1000&&i<u.length-1){n/=1000;i++}return `${n.toFixed(n>=100?0:n>=10?1:2)} ${u[i]}`};
function renderBackup(s){const blocked=s.space_check==="blocked";$("backup-safety").classList.toggle("blocked",blocked);$("backup-heading").textContent=blocked?"Blocked — not enough space for a safe backup":"Backup required before replacement";$("backup-space").textContent=s.destination_bytes_required!=null?`Last space check: ${fmt(s.destination_bytes_free)} free; ${fmt(s.destination_bytes_required)} required, including ${fmt(s.backup_bytes_required)} for backups and ${fmt(s.reserve_bytes)} safety reserve. Space is checked again before replacement.`:"Destination space has not been checked yet.";const r=s.receipt||{};$("backup-location").textContent=s.pending_backup?`Pending backup on the destination: ${s.pending_backup}. Use Check recovery below; a saved path alone does not prove the backup is intact.`:r.backup_verified?`Last verified backup on the destination: ${r.backup}. File contents, tree structure and link targets checked before replacement.`:"No verified backup recorded for this migration."}
async function api(path,options={}){const response=await fetch(path,{...options,headers:{"X-Codex-Migrate-Token":token,"Content-Type":"application/json",...(options.headers||{})}});const body=await response.json();if(!response.ok)throw new Error(body.error||`Request failed (${response.status})`);renderBackup(body);return body}
function render(s){latestState=s;const p=Math.max(0,Math.min(100,Number(s.percent)||0));$("percent").textContent=`${p.toFixed(p===100?0:1)}%`;$("bar").style.width=`${p}%`;$("bar").parentElement.setAttribute("aria-valuenow",String(p));$("phase").textContent=String(s.phase||"unknown").replaceAll("_"," ");$("status").textContent=String(s.status||"unknown").replaceAll("_"," ");$("message").textContent=s.message||"";$("route").textContent=s.route||"—";$("bytes").textContent=`${fmt(s.bytes_staged||0)} / ${fmt(s.bytes_total||0)}`;$("item").textContent=s.current_item||"—";$("warning").style.display=s.warning?"block":"none";$("warning").textContent=s.warning||"";$("error").style.display=s.error?"block":"none";$("error").textContent=s.error||"";const c=s.config||{};$("codex-scope").textContent=`${c.source_home||"—"}/.codex → ${c.target_home||"—"}/.codex`;$("ssh-target").textContent=`${c.target||"—"} · ${c.target_home||"—"}`;const roots=Array.isArray(c.workspace_roots)?c.workspace_roots:[];$("workspace-count").textContent=String(roots.length);$("workspace-list").replaceChildren(...roots.map(root=>{const li=document.createElement("li");const prefix=`${c.source_home}/`;const relative=root.startsWith(prefix)?root.slice(prefix.length):root;li.textContent=`${root} → ${c.target_home}/${relative}`;return li}));const active=s.status==="running";const canStart=["idle","ready"].includes(s.status);const canFinalize=s.status==="ready_to_finalize"||(s.status==="waiting"&&["close_source_codex","close_target_codex"].includes(s.phase));$("inspect").disabled=active;$("start").disabled=!canStart||!s.apply;$("pause").disabled=!active||!["staging","final_delta"].includes(s.phase);$("resume").disabled=!s.apply||!['paused','cancelled','failed','interrupted'].includes(s.status);$("finalize").disabled=!canFinalize||!s.apply;$("cancel").disabled=!((active&&["inspecting","staging","final_delta"].includes(s.phase))||s.status==="paused");}
function renderSkills(s){
  const installed=s.status==='complete'||['path_compatibility','git_verification'].includes(s.phase);
  $("codex-state-proof").hidden=s.migration_mode==="skills";
  $("codex-state-proof").textContent=installed&&s.receipt?.codex_state_content_verified===true?"Retained Codex state matched the source before and after installation, before database checks. Authentication and runtime exclusions apply.":installed?"No retained Codex state verification was recorded for this migration.":"Retained Codex state verification is pending.";
  if(s.status==="running"&&s.phase==="verifying_sources")$("cancel").disabled=false;
  renderGit(s);
  const waiting=s.status==="ready_to_finalize"||s.status==="waiting"||["verifying_sources","installing"].includes(s.phase);
  $("percent").hidden=waiting;$("bar").parentElement.hidden=waiting;
  $("size-heading").textContent=s.status==="complete"?"Migration size estimate":"Staged / estimated total";
  if(s.status==="complete")$("bytes").textContent=fmt(s.bytes_total||0);
  const repair=s.migration_mode==="skills";
  const skills=repair?s.inventory?.skill_exports:s.inventory?.personal_skills;
  const verified=installed?(repair?s.receipt?.skills_verified:s.receipt?.personal_skills_verified):null;
  $("skill-count").textContent=Array.isArray(skills)?`${skills.length} selected${verified!=null?` · ${verified} verified`:" · not yet verified"}`:"Not inspected yet";
  $("skill-list").replaceChildren(...(skills||[]).map(skill=>{const li=document.createElement("li");li.textContent=`${skill.name} → ${skill.destination}`;return li}));
  if(repair){
    document.querySelector(".lede").textContent="Move selected custom skills with verified backups. Conversations, settings and whole projects stay untouched.";
    $("codex-scope").textContent="Not included — conversations and configuration stay unchanged";
    $("workspace-heading").textContent="Folders searched for workspace skills (not copied whole):";
    if(!(s.components||[]).includes("workspace-skills")){$("workspace-count").textContent="0";$("workspace-list").replaceChildren();}
    else{$("workspace-list").replaceChildren(...(s.config?.workspace_roots||[]).map(root=>{const li=document.createElement("li");li.textContent=root;return li}));}
    $("skill-heading").textContent="Selected skills:";
    $("skill-explanation").textContent="Only skills from the chosen categories are included. Each listed destination is backed up before replacement. Other skills and files are kept.";
    $("protection-explanation").textContent="The source is never modified. Only listed skill destinations are replaced after verified backups. Codex conversations, configuration and authentication are not copied or replaced. Interrupted staging is kept so Resume can continue.";
  }
  renderRecovery(s);
  renderPaths(s);
  renderGitCheck(s);
}
let gitWasChecking=false;
function renderGitCheck(s){
  const g=s.git_verification||{}, checking=g.status==='checking', pathsChecking=s.path_compatibility?.status==='checking', focused=document.activeElement?.id;
  const installed=Boolean(s.receipt), full=s.migration_mode!=='skills';
  const busy=checking||(pathsChecking&&installed&&full);
  $('git-check-help').hidden=!full||!installed;
  $('git-check-message').textContent=pathsChecking?'Checking home paths before Git. Safe to stop; no files are being changed.':(g.message||'Git checks run after installation and home-path verification.')+(g.checked_at?` Checked at ${g.checked_at}.`:'');
  if(busy&&focused==='check_git')$('git-check-message').focus();
  $('check_git').disabled=!full||!installed||s.status==='running'||busy||s.recovery?.status==='checking'||['restoring','restored','recovery_required'].includes(s.phase)||(s.recovery_attempt&&s.recovery_attempt.resolved!==true);
  $('stop_git').disabled=!busy;
  if(full&&installed)for(const name of ['inspect','start','pause','resume','finalize','cancel'])$(name).disabled=true;
  if(checking)for(const name of ['check_paths','check_recovery','restore_recovery'])$(name).disabled=true;
  if(s.phase==='git_verification'){$('bar').parentElement.hidden=true;$('percent').textContent='—';}
  if(!busy&&gitWasChecking&&['git-check-message','stop_git'].includes(focused))$('check_git').focus();
  gitWasChecking=busy;
}
let pathsWereChecking=false;
function renderPaths(s){
  const p=s.path_compatibility||{}, checking=p.status==='checking', focused=document.activeElement?.id;
  $('path-help').hidden=s.migration_mode==='skills';
  $('path-next').hidden=s.migration_mode==='skills'||s.phase!=='path_compatibility';
  $('check_paths').disabled=s.status==='running'||checking||['restoring','recovery_required'].includes(s.phase)||(s.recovery_attempt&&s.recovery_attempt.resolved!==true)||s.recovery?.status==='checking';
  $('path-message').textContent=(p.message||'Home paths have not been checked.')+(p.checked_at?` Checked at ${p.checked_at}.`:'');
  $('path-command').hidden=!s.compatibility_command;
  $('compat').textContent=s.compatibility_command||'';
  if(checking||s.phase==='path_compatibility')for(const name of ['inspect','start','pause','resume','finalize','cancel'])$(name).disabled=true;
  if(checking)for(const name of ['check_recovery','restore_recovery'])$(name).disabled=true;
  if(s.phase==='path_compatibility'){$('bar').parentElement.hidden=true;$('percent').textContent='—';}
  if(checking&&focused==='check_paths')$('path-message').focus();
  else if(!checking&&pathsWereChecking&&focused==='path-message'){
    if(s.git_verification?.status==='checking'){$('git-check-help').open=true;$('git-check-message').focus();}
    else $('check_paths').focus();
  }
  pathsWereChecking=checking;
}
function renderGit(s){
  const installed=s.status==='complete'||['path_compatibility','git_verification'].includes(s.phase);
  $("git-scope").hidden=s.migration_mode==="skills";
  $("workspace-proof").textContent=installed&&s.receipt?.workspace_content_verified===true?`Workspace content verification passed for ${s.receipt.workspace_roots_verified} root(s). File bytes, names, permissions and link text matched before and after installation.`:installed?"No workspace-content verification was recorded for this migration.":"Workspace content verification is pending.";
  const inventory=s.inventory||{};
  const repos=inventory.git_details, missing=inventory.git_missing_paths||[], issues=inventory.git_issues||[], warnings=inventory.git_warnings||[];
  $("git-summary").textContent=!Array.isArray(repos)?"Git scope has not been inspected with this version.":`${repos.length} Git locations found. ${issues.length?"Metadata needs review before transfer.":missing.length?`${missing.length} additional folder(s) required before transfer.`:repos.length?"Inspected storage dependencies are inside the selected scope.":"No repositories were found in the searched folders."}`;
  const list=(id,items)=>$(id).replaceChildren(...items.map(text=>{const li=document.createElement("li");li.textContent=text;return li}));
  list("git-list",(repos||[]).map(repo=>`${repo.path} — ${{checkout:"repository",linked:"linked Git directory",storage:"Git storage"}[repo.kind]||"Git location"}`));
  list("git-required",missing.map(path=>`Required folder not selected: ${path}`));
  list("git-issues",[...issues,...warnings]);
}
function renderEvents(events){const rows=(events||[]).map(event=>{const li=document.createElement('li');const recovery=event.recovery_status&&event.recovery_status!=='not_checked'?` · recovery check: ${event.recovery_status.replaceAll('_',' ')}`:'';const paths=event.path_status&&event.path_status!=='not_checked'?` · home paths: ${event.path_status.replaceAll('_',' ')}`:'';const git=event.git_status&&event.git_status!=='not_checked'?` · Git: ${event.git_status.replaceAll('_',' ')}`:'';li.textContent=`${event.at||'Time unavailable'} · ${event.phase.replaceAll('_',' ')} · ${event.status}${event.failure_category==='none'?'':` · ${event.failure_category.replaceAll('_',' ')}`}${recovery}${paths}${git}`;return li});if(!rows.length){const li=document.createElement('li');li.textContent='No events recorded yet.';rows.push(li)}$('migration-events').replaceChildren(...rows)}
function renderRecovery(s){
  const r=s.recovery||{}, checking=r.status==='checking', restoring=r.status==='restoring', attempt=s.recovery_attempt||{};
  const unresolved=['restoring','recovery_required'].includes(s.phase)||(s.recovery_attempt&&attempt.resolved!==true);
  const focused=document.activeElement?.id;
  $('check_recovery').disabled=s.status==='running'||checking||restoring;
  $('stop_recovery').disabled=!checking;
  const resumable=['restore_incomplete','restore_pending_cleanup'].includes(r.status)&&attempt.reference;
  $('restore_recovery').disabled=!s.apply||s.status==='running'||checking||restoring||!(r.status==='backup_verified'||resumable);
  $('restore_recovery').textContent=resumable?'Resume restoration':'Restore backup';
  if(checking||restoring||unresolved)for(const name of ['inspect','start','pause','resume','finalize','cancel'])$(name).disabled=true;
  const recoveryPhase=['restoring','restored','recovery_required'].includes(s.phase);
  if(recoveryPhase)$('bar').parentElement.hidden=true;
  if(recoveryPhase)$('percent').textContent='—';
  $('recovery-message').textContent=r.message||'No recovery check has run.';
  $('recovery-details').hidden=!r.checked_at;
  $('recovery-time').textContent=r.checked_at?`Checked at ${r.checked_at}. This is a point-in-time result, not a live guarantee.`:'';
  const backup=r.backup||attempt.reference?.backup;
  if(recoveryPhase&&backup){$('backup-heading').textContent='Recovery backup';$('backup-location').textContent=`Recorded recovery backup: ${backup}. See Last check details for its verification status; keep this backup and preserved files intact.`;}
  $('recovery-backup').textContent=backup?`Destination backup: ${backup}`:'';
  $('recovery-terminal').textContent=r.terminal_phase?`An earlier receipt records ${r.terminal_phase}. Current destination contents and usability have not been verified by this check.`:'';
  const items=r.items||attempt.inspection?.items||[];
  $('recovery-items').replaceChildren(...items.map(item=>{const li=document.createElement('li');li.textContent=!r.items?`${item.original} — confirmed restoration scope; current presence is not verified by this result.`:'restored_matches' in item?`${item.original} — restored entry ${item.restored_present?'present':'absent'}, ${item.restored_matches?'matches':'does not match'} recovery evidence. Preserved entry: ${item.preserved} — ${item.preserved_present?'present':'absent'}, ${item.preserved_matches?'matches':'does not match'} recovery evidence.`:`${item.original} — ${item.existed?'backup verified':'originally absent'}; ${item.current_present?'current destination entry present':'current destination entry absent'}`;return li}));
  if((checking&&focused==='check_recovery')||(restoring&&focused==='restore_recovery'))$('recovery-message').focus();
  else if(!checking&&!restoring&&recoveryWasChecking&&['recovery-message','stop_recovery'].includes(focused))$('check_recovery').focus();
  recoveryWasChecking=checking||restoring;
}
async function refresh(){try{const s=await api("/api/status");render(s);renderSkills(s);renderEvents(s.support_events)}catch(error){$("error").style.display="block";$("error").textContent=error.message}}
async function action(name){const c=latestState.config||{};const confirmation=latestState.migration_mode==="skills"?`Back up, then replace ${latestState.inventory?.skill_exports?.length||0} listed skill(s) on ${c.target}? Conversations, configuration and whole repositories will not be migrated. Other skills will be kept.`:`Back up, then replace ${c.target_home}/.codex, ${c.workspace_roots?.length||0} selected workspace root(s), and ${latestState.inventory?.personal_skills?.length||0} personal skill(s) on ${c.target}? Other destination skills will be kept.`;if(name==="finalize"&&!confirm(confirmation))return;try{const s=await api("/api/action",{method:"POST",body:JSON.stringify({action:name,confirmed:name==="finalize"})});render(s);renderSkills(s)}catch(error){$("error").style.display="block";$("error").textContent=error.message}}
for(const name of ["inspect","start","pause","resume","finalize","cancel","check_recovery","stop_recovery","check_paths","check_git","stop_git"]){$(name).addEventListener("click",()=>action(name))}
$('copy-path-command').addEventListener('click',async()=>{try{await navigator.clipboard.writeText(latestState.compatibility_command||'');$('path-message').textContent='Command copied. Run it on the new Mac, then check home paths again.'}catch(error){$('path-message').textContent='Clipboard access was unavailable. Select and copy the command below.'}});
$('path-next').addEventListener('click',event=>{event.preventDefault();$('path-help').open=true;$('path-help').scrollIntoView({block:'start'});$('path-help').querySelector('summary').focus()});
$('restore_recovery').addEventListener('click',async()=>{
  const r=latestState.recovery||{}, attempt=latestState.recovery_attempt||{}, c=latestState.config||{};
  const id=r.status==='backup_verified'?r.transaction_id:attempt.reference?.transaction_id;
  const items=r.status==='backup_verified'?r.items:attempt.inspection?.items;
  if(!id||!Array.isArray(items))return;
  const paths=items.slice(0,5).map(item=>item.original).join('\n');
  if(!confirm(`Restore the previous destination on ${c.target}, replacing all ${items.length} listed path(s)?\n\n${paths}${items.length>5?'\n…see Last check details for all paths.':''}\n\nCurrent entries will be kept separately, not merged. Close destination Codex and all apps writing these files. This protected step may take time; keep both Macs connected.`))return;
  try{const s=await api('/api/action',{method:'POST',body:JSON.stringify({action:'restore_recovery',confirmed:true,transaction_id:id})});render(s);renderSkills(s)}catch(error){$('error').style.display='block';$('error').textContent=error.message}
});
refresh();setInterval(refresh,2500);
</script>
</body></html>"""
HTML = with_support(HTML)


class LoopbackHTTPServer(ThreadingHTTPServer):
    def server_bind(self) -> None:
        # HTTPServer normally reverse-resolves even 127.0.0.1. This dashboard
        # only needs its bound address; DNS must not delay local startup.
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


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

            def _html(self, document: str) -> None:
                encoded = document.encode("utf-8")
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

            def do_GET(self) -> None:
                if self.path == "/" or self.path.startswith("/?"):
                    self._html(HTML)
                    return
                if self.path == "/api/support-report":
                    if not self._authorized():
                        self._json(403, {"error": "Missing or invalid local control token"})
                        return
                    try:
                        self._json(200, diagnostic_report(dashboard.state.read()))
                    except Exception:
                        self._json(409, {"error": "Migration state could not be read. Email support; keep staging and backups."})
                    return
                if self.path == "/api/status":
                    if not self._authorized():
                        self._json(403, {"error": "Missing or invalid local control token"})
                        return
                    try:
                        body = dashboard.state.read()
                    except Exception:
                        self._json(409, {"error": "Migration state could not be read. Email support; keep staging and backups."})
                        return
                    body["support_events"] = diagnostic_report(body)["recent_events"]
                    body = public_state(body)
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
                    if action in ("start", "resume", "finalize", "restore_recovery") and not dashboard.engine.config.apply:
                        raise MigrationError("Changes are disabled; restart with --apply to enable migration")
                    if action == "check_recovery":
                        dashboard.engine.start_recovery_check()
                    elif action == "check_paths":
                        dashboard.engine.start_path_check()
                    elif action == "check_git":
                        dashboard.engine.start_git_check()
                    elif action == "stop_git":
                        dashboard.engine.stop_git_check()
                    elif action == "stop_recovery":
                        dashboard.engine.stop_recovery_check()
                    elif action == "restore_recovery":
                        if payload.get("confirmed") is not True:
                            raise MigrationError("Restoration requires explicit confirmation")
                        dashboard.engine.start_restore_recovery(payload.get("transaction_id"))
                    elif action == "inspect":
                        if dashboard.state.read().get("status") == "running":
                            raise MigrationError("Wait for the current migration action to finish")
                        dashboard.engine.start_inspection()
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
                    body = public_state(body)
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
            if not self.can_shutdown():
                print("An operation is active. Use Stop safely in the dashboard, "
                      "or wait for installation and verification to finish.", flush=True)
                return
            raise KeyboardInterrupt

        if threading.current_thread() is threading.main_thread():
            for name in ("SIGINT", "SIGTERM", "SIGHUP"):
                if hasattr(signal, name):
                    value = getattr(signal, name)
                    previous_handlers[value] = signal.getsignal(value)
                    signal.signal(value, interrupt_for_shutdown)
        try:
            self.server = LoopbackHTTPServer((self.host, self.port), self._handler())
            url = "http://%s:%d/#token=%s" % (self.host, self.server.server_port, self.token)
            print("Codex Migrate dashboard: %s" % url, flush=True)
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

    def can_shutdown(self) -> bool:
        current = self.state.read()
        return not (current.get("status") == "running" and current.get("phase") == "restoring")
