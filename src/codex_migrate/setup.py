"""Browser-first setup, local persistence and native folder selection.

This server never proxies workspace contents. It attaches the same Dashboard
and MigrationEngine used by the CLI after explicit validated configuration.
"""
from __future__ import annotations

import hashlib
import json
from contextlib import nullcontext
from pathlib import Path
import platform
import secrets
import subprocess
import tempfile
import threading
import time
import uuid
from urllib.parse import parse_qs, urlsplit

from codex_migrate.config import MigrationConfig, SSHOptions
from codex_migrate.dashboard import Dashboard
from codex_migrate.migration import MigrationEngine, MigrationError
from codex_migrate.component_migration import ComponentMigrationEngine
from codex_migrate.state import StateStore
from codex_migrate.support import with_support, SUPPORT_HTML
from codex_migrate.pairing import Pairing
from codex_migrate.vault import inspect as inspect_vault
from codex_migrate.vault import markdown as vault_markdown
from codex_migrate.vault import _find_transcript, markdown_chunks, read_thread, read_thread_page, search as search_vault
from codex_migrate.vault_backup import backup as backup_vault
from codex_migrate.vault_backup import plan as plan_vault_backup
from codex_migrate.vault_dashboard import VAULT_HTML
from codex_migrate.vault_history import search_titles, thread_timeline
from codex_migrate.vault_recovery import export_recovery_key
from codex_migrate.vault_recovery import list_snapshots as list_vault_snapshots
from codex_migrate.vault_recovery import snapshot_catalog
from codex_migrate.vault_recovery import restore_snapshot as restore_vault_snapshot
from codex_migrate.vault_install import install_snapshot as install_vault_snapshot
from codex_migrate.vault_install import install_thread as install_vault_thread
from codex_migrate.vault_install import install_status as persistent_install_status
from codex_migrate.vault_install import recover_interrupted_install
from codex_migrate.vault_schedule import (
    install_schedule as install_vault_schedule,
    remove_schedule as remove_vault_schedule,
    schedule_status as vault_schedule_status,
)
from codex_migrate.vault_storage import classify_vault_storage

FOLDER_PICKER_ERROR = (
    "Folder selection could not finish. Close any open folder dialog and try again, "
    "or use Review or edit folder paths. If macOS denied access, review this app's "
    "permissions in System Settings. Your existing selection is unchanged."
)

SETUP_HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="data:,">
<title>Codex Migrate — Vault + Migration</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#080b10;color:#f7f8fa;font:500 17px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;overflow-wrap:anywhere}
main{width:min(800px,calc(100% - 32px));margin:40px auto}h1{font-size:clamp(32px,6vw,48px);line-height:1.1}h2{font-size:24px}p{color:#cbd2df}section,fieldset{background:#111722;border:1px solid #465268;border-radius:16px;padding:24px;margin:24px 0;min-width:0}
label{display:block;margin:16px 0 6px}input,textarea,button,select{font:inherit}input:not([type=checkbox]),textarea,select{display:block;width:100%;padding:12px;border:1px solid #8996ad;border-radius:8px;color:#f7f8fa;background:#080b10}textarea{min-height:120px}button,a.button{display:inline-block;padding:12px 18px;border:1px solid #a08bd3;border-radius:9px;background:#6042a6;color:white;font-weight:700;cursor:pointer;text-decoration:none;max-width:100%;white-space:normal}button:disabled{opacity:.6;cursor:wait}.controls{display:flex;gap:12px;flex-wrap:wrap}.check{display:flex;gap:12px;align-items:flex-start}.check input{width:22px;height:22px;flex:none;margin-top:4px}a{color:#d9cdff}:focus-visible{outline:3px solid #d9cdff;outline-offset:4px}#error{color:#ffc3c8}#message{color:#cbd2df}footer{font-size:15px;color:#cbd2df}legend{font-weight:700;font-size:24px}[hidden]{display:none!important}@media(max-width:480px){section,fieldset{padding:16px}main{margin:24px auto}}
.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}.setup-step h2{margin-top:0}button.secondary{background:transparent;border-color:#8996ad}#step-progress{color:#d9cdff;font-weight:700}#review dt{font-size:15px;color:#cbd2df}#review dd{margin:0 0 16px;font-weight:700}details{margin:18px 0}summary{cursor:pointer;font-weight:650}#message:empty{display:none}#folder-message:empty,#folder-error:empty{margin:0}#folder-error{color:#ffc3c8}#folder-message{color:#cbd2df}
.app{min-height:100vh;display:grid;grid-template-columns:238px 1fr}.sidebar{position:sticky;top:0;height:100vh;padding:28px 18px 24px;border-right:1px solid #273145;background:#0c1018;display:flex;flex-direction:column}.brand{display:flex;gap:12px;align-items:center;padding:0 8px 26px}.brand-mark{width:36px;height:36px;display:grid;place-items:center;border-radius:11px;background:linear-gradient(145deg,#9475ff,#5735d6);font-size:14px;font-weight:850;box-shadow:0 10px 30px #6f4cff44}.brand strong,.brand small{display:block}.brand small{color:#aeb8ca;font-size:12px}.nav{display:grid;gap:8px}.nav a{display:flex;align-items:center;gap:12px;padding:12px 14px;color:#aeb8ca;border-radius:11px;text-decoration:none;font-weight:700}.nav a:hover,.nav a.active{color:white;background:#1d2434}.nav-icon{width:18px;text-align:center;color:#a991ff}.protection{margin-top:auto;border-top:1px solid #273145;padding:18px 8px 0;font-size:13px;color:#aeb8ca}.protection strong{color:#f7f8fa}.content{min-width:0}.overview-head{margin:16px 0 28px}.overview-head h1{font-size:clamp(40px,6vw,64px);letter-spacing:-.045em;line-height:1;margin:10px 0}.overview-head p{font-size:18px;max-width:720px}.health{display:flex;align-items:center;justify-content:space-between;gap:20px;border:1px solid #344057;border-radius:18px;padding:22px;background:#111722}.health-copy{display:flex;gap:15px;align-items:center}.health-icon{width:44px;height:44px;display:grid;place-items:center;border-radius:14px;background:#103b2d;color:#57e1a5;font-size:24px}.health.attention .health-icon{background:#3b2b12;color:#ffd58a}.health span,.health strong{display:block}.health span{color:#9eabc0;font-size:13px;text-transform:uppercase;letter-spacing:.12em}.health strong{font-size:22px}.job-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:18px 0}.job-card{display:block;min-height:190px;padding:22px;border:1px solid #344057;border-radius:18px;background:#111722;color:#f7f8fa;text-decoration:none}.job-card small{color:#c3adff;font-weight:800;letter-spacing:.12em}.job-card h2{margin:24px 0 8px}.job-card p{font-size:15px}.job-card strong{display:block;margin-top:18px}.move-head{display:flex;align-items:flex-start;justify-content:space-between;gap:20px}.move-head h1{margin:8px 0}.move-kicker{color:#a991ff;font-weight:750}.view-overview #move-view{display:none}.view-move #overview-view{display:none}.view-move main{width:min(900px,calc(100% - 48px))}.view-move #move-view>h1{font-size:clamp(38px,6vw,58px);letter-spacing:-.045em;margin-bottom:4px}.view-move #move-view>p{font-size:18px}.view-move section,.view-move fieldset{border-color:#344057;background:#111722}.view-move #step-progress{margin:28px 0 8px;text-transform:uppercase;letter-spacing:.12em;font-size:14px}
@media(max-width:820px){.app{display:block}.sidebar{position:static;width:auto;height:auto;padding:16px}.brand{padding-bottom:12px}.nav{display:flex;overflow-x:auto}.nav a{white-space:nowrap}.protection{display:none}.job-grid{grid-template-columns:1fr}.job-card{min-height:0}}
@media(max-width:520px){.health{display:block}.health-copy{align-items:flex-start}.health a.button{display:block;width:100%;margin-top:18px;text-align:center}}
</style>
</head>
<body>
<div class="app">
<aside class="sidebar">
<div class="brand"><div class="brand-mark">CM</div><div><strong>Codex Migrate</strong><small>Vault + Migration</small></div></div>
<nav class="nav" aria-label="Product">
<a data-route="overview" href="/?view=overview"><span class="nav-icon">⌂</span>Overview</a>
<a data-route="backup" href="/vault?view=backup"><span class="nav-icon">⟳</span>Backups</a>
<a data-route="conversations" href="/vault?view=conversations"><span class="nav-icon">⌕</span>Conversations</a>
<a data-route="recovery" href="/vault?view=recovery"><span class="nav-icon">↺</span>Recovery</a>
<a data-route="move" href="/?view=move"><span class="nav-icon">⇢</span>Move Macs</a>
</nav>
<div class="protection"><strong>This Mac stays local</strong><br>Conversation content is not sent to Codex Migrate servers.</div>
</aside>
<div class="content">
<main>
<section id="overview-view">
<header class="overview-head"><div class="move-kicker">Overview</div><h1>Your Codex work,<br>safe and searchable.</h1><p>One place to protect your history, find old conversations, and move to another Mac without breaking your setup.</p></header>
<div class="health" id="overview-health-card"><div class="health-copy"><div class="health-icon" id="overview-health-icon">·</div><div><span>Backup health</span><strong id="overview-health">Checking protection…</strong><p id="overview-health-detail">Reading this Mac’s local Vault status.</p></div></div><a class="button secondary" data-overview-route="backup" href="/vault?view=backup">Back up now</a></div>
<div class="job-grid">
<a class="job-card" data-overview-route="backup" href="/vault?view=backup"><small>01</small><h2>Back up this Mac</h2><p>Encrypted, versioned backups in a folder you control.</p><strong>Manage backups →</strong></a>
<a class="job-card" data-overview-route="conversations" href="/vault?view=conversations"><small>02</small><h2>Find a conversation</h2><p>Search active and archived Codex threads from one clean library.</p><strong>Search history →</strong></a>
<a class="job-card" data-overview-route="move" href="/?view=move"><small>03</small><h2>Move to another Mac</h2><p>Carry over your Codex environment and pick up where you stopped.</p><strong>Start a migration →</strong></a>
</div>
</section>
<div id="move-view">
<a class="support-link" href="#migration-help">Help / Email support</a>
<div class="move-kicker">Move Macs</div>
<h1>Move your Codex work.</h1>
<p>Your conversations, skills, and unfinished work. Directly from this Mac to your new one.</p>
<button type="button" class="secondary" id="receiver-toggle">I’m on the new Mac</button>
<div id="error" role="alert">
</div>
<p id="message" role="status" aria-live="polite">Connecting to your local helper…</p>
<section id="receiver" hidden>
<h2 tabindex="-1">Prepare this new Mac</h2>
<p>First, install Codex and sign in. In System Settings → General → Sharing, enable Remote Login for your account.</p>
<div id="receiver-request-area">
<label for="request-card">Paste the connection card from your old Mac</label>
<textarea id="request-card" spellcheck="false" autocomplete="off">
</textarea>
<p>Approve only a card you just created on your own old Mac. This grants that Mac SSH access to read and change files in this account for seven days. It does not start a migration.</p>
<button type="button" id="approve-card">Approve this connection for seven days</button>
</div>
<div id="reply-area" hidden>
<p>Approved. Copy the reply and paste it into Codex Migrate on your old Mac.</p>
<button type="button" id="copy-reply">Copy reply</button>
<details>
<summary>View reply card</summary>
<label for="reply-card">Reply for your old Mac</label>
<textarea id="reply-card" readonly spellcheck="false">
</textarea>
</details>
</div>
<details>
<summary>Remove connection access</summary>
<p>After your migration is complete, remove the access granted by this helper. Other SSH connections are kept. Do not do this during migration or recovery.</p>
<button type="button" class="secondary" id="revoke-pair">Remove this connection’s access</button>
</details>
</section>
<section id="attached" hidden>
<h2>Your migration is configured</h2>
<p>Continue to its status, backup checks, pause/resume controls and recovery guidance. Keep the same destination and scope when resuming. Changing scope while staged data exists requires reviewing that migration’s recovery instructions; restarting alone does not adopt it.</p>
<a class="button" id="continue" href="/migration">Open migration dashboard</a>
</section>
<p id="step-progress" aria-live="polite">Step 1 of 3 · Your new Mac</p>
<form id="setup" novalidate>
<fieldset id="fields" disabled>
<legend class="sr-only">Migration setup</legend>
<div id="step-1" class="setup-step">
<h2 tabindex="-1">Your new Mac</h2>
<p>Connect both Macs to Wi-Fi, or use a compatible USB-C/Thunderbolt connection.</p>
<div id="pair-source">
<p>Open Codex Migrate on both Macs. Create a card here, then approve it in the new Mac’s browser. No Terminal commands or passwords.</p>
<button type="button" id="create-card">Create connection card</button>
<div id="request-area" hidden>
<p>On the new Mac, choose “I’m on the new Mac” and paste this card.</p>
<button type="button" id="copy-request">Copy card</button>
<details>
<summary>View connection card</summary>
<label for="source-card">Connection card for your new Mac</label>
<textarea id="source-card" readonly spellcheck="false">
</textarea>
</details>
<label for="accepted-card">Paste the reply from your new Mac</label>
<textarea id="accepted-card" spellcheck="false" autocomplete="off">
</textarea>
<p>Use only the reply shown on your own new Mac. It supplies that Mac’s verified local SSH identity—not an identity discovered on the network.</p>
<button type="button" id="accept-card">Use this new Mac</button>
</div>
</div>
<p id="paired-status" role="status" hidden>
</p>
<details id="manual-connection">
<summary>Use an existing SSH connection instead</summary>
<label for="computer">New Mac’s name or address</label>
<input id="computer" autocomplete="off" placeholder="e.g. Joshuas-MacBook-Pro.local" required>
<label for="username">Your username on the new Mac</label>
<input id="username" autocomplete="off" placeholder="e.g. joshua" required>
<input id="target" type="hidden">
<details>
<summary>Help finding and connecting your Mac</summary>
<p>On the new Mac, open System Settings → General → Sharing → Remote Login. Turn it on for your account; the login address shown there contains your username and Mac’s address. Install Codex there and sign in once.</p>
<p>The current build needs SSH key login set up between the Macs. Connect once in Terminal using <code>ssh new-user@new-mac.local</code> and verify the host fingerprint. An interactive password prompt is not supported yet. A charging-only cable cannot carry the transfer.</p>
</details>
<details>
<summary>Advanced connection settings</summary>
<label for="target-home">New Mac’s home folder</label>
<input id="target-home" autocomplete="off" placeholder="/Users/username" required>
<label for="identity">Existing SSH key path (optional)</label>
<input id="identity" autocomplete="off" spellcheck="false" aria-describedby="key-help">
<p id="key-help">Leave empty to use your SSH configuration. Selecting a key does not add it to the migration, and this selection is not saved. A key stored inside a selected workspace is copied with that workspace.</p>
</details>
</details>
<details>
<summary>Start a fresh connection</summary>
<p>Use this if your seven-day connection has expired. Previous local connection files are kept. On the new Mac, remove the previous connection’s access before approving the new card.</p>
<button type="button" class="secondary" id="restart-pair">Start a new connection</button>
</details>
<div class="controls">
<button type="button" id="next-1">Continue</button>
</div>
</div>
<div id="step-2" class="setup-step" hidden>
<h2 tabindex="-1">What would you like to move?</h2>
<label for="mode">What do you want to move?</label>
<select id="mode">
<option value="full">Full Codex migration</option>
<option value="skills">Custom skills only</option>
</select>
<fieldset id="skill-components" hidden>
<legend>Skills to include</legend>
<label class="check">
<input type="checkbox" id="personal-skills" checked>
<span>Personal custom skills (.agents/skills and legacy .codex/skills)</span>
</label>
<label class="check">
<input type="checkbox" id="workspace-skills">
<span>Workspace skills inside the project folders selected below</span>
</label>
<p>Skills only: conversations, configuration and whole repositories are not copied. Other destination skills are kept. Inspect the list, stage it, then confirm Finalize separately.</p>
</fieldset>
<p id="folder-summary" aria-live="polite">No project folders selected.</p>
<div class="controls">
<button type="button" id="folders">Choose folders on this Mac…</button>
<button type="button" id="suggest" class="secondary">Suggest common folders</button>
</div>
<p id="folder-error" role="alert">
</p>
<p id="folder-message" role="status" aria-live="polite">
</p>
<details>
<summary>Review or edit folder paths</summary>
<label for="workspaces" id="workspace-label">Workspace folders on this Mac, one per line</label>
<textarea id="workspaces" spellcheck="false" aria-describedby="scope-help">
</textarea>
</details>
<p id="scope-help">Selected folders include unfinished work and any secrets stored inside them. Full migration includes Codex state and personal skills; other folders are not automatically included.</p>
<div class="controls">
<button type="button" class="secondary" id="back-2">Back</button>
<button type="button" id="next-2">Review migration</button>
</div>
</div>
<div id="step-3" class="setup-step" hidden>
<h2 tabindex="-1">Ready to check both Macs</h2>
<dl id="review">
</dl>
<p>We’ll check the connection and available space before you start. A verified backup is required before replacing destination data.</p>
<p id="replacement-note">This replaces selected destination data; it does not merge separate work. Keep your old Mac intact.</p>
<details>
<summary>What gets saved between runs?</summary>
<p>Your destination and folder selection are saved privately on this Mac. Changes reset to disabled on each launch; SSH key selections are not saved.</p>
</details>
<label class="check">
<input id="apply" type="checkbox">
<span>Allow this migration to copy files to my new Mac. I’ll review the checks before starting.</span>
</label>
<div class="controls">
<button type="button" class="secondary" id="back-3">Back</button>
<button type="submit" id="open">Continue to migration</button>
</div>
</div>
</fieldset>
</form>
<details>
<summary>Resuming a migration or only restoring skills?</summary>
<p>For migrations started in this browser setup, reopen the helper after interruption, review the restored setup, enable changes if appropriate, and use Resume in the dashboard. Staged data and backup receipts remain on your Macs. Never delete them just because a progress bar reaches 100%.</p>
<p>Already started with the CLI or native setup? Resume using that same entry point and configuration. This browser setup does not import those older migration records, and it will not adopt or overwrite their staging.</p>
<p>Choose Custom skills only above for a smaller repair. It has its own saved staging, pause/resume controls and verified destination backups; a full migration’s staging is left alone.</p>
</details>
</div>
<footer>Codex Migrate is independent software. Not affiliated with or endorsed by OpenAI. Mac-to-Mac only.</footer>
</main>
</div>
</div>
<script>
const $=id=>document.getElementById(id);
const storageKey="codex-migrate-token:"+location.origin;
const incoming=new URLSearchParams(location.hash.slice(1)).get("token");
if(incoming)sessionStorage.setItem(storageKey,incoming);
const token=incoming||sessionStorage.getItem(storageKey)||"";
history.replaceState(null,"",location.pathname+location.search);
const requestedView=new URLSearchParams(location.search).get("view");
const view=requestedView==="move"?"move":"overview";
document.body.classList.add("view-"+view);
for(const link of document.querySelectorAll("[data-route]")){link.classList.toggle("active",link.dataset.route===view);link.href=link.getAttribute("href")+"#token="+encodeURIComponent(token)}
for(const link of document.querySelectorAll("[data-overview-route]")){link.href=link.getAttribute("href")+"#token="+encodeURIComponent(token)}
const roots=()=>$("workspaces").value.split("\n").map(x=>x.trim()).filter(Boolean);
const fullScopeHelp=$("scope-help").textContent;
const fullKeyHelp=$("key-help").textContent;
let step=1;
let paired=false;
let connectionBlocked=false;
function pairingView(){
  $("pair-source").hidden=paired;
  $("paired-status").hidden=!paired;
  $("paired-status").textContent=paired?"Selected: "+$("target").value+". Connection checks run before transfer.":"";
}
function manualEdit(){paired=false;connectionBlocked=false;pairingView();syncDestination();}
function syncDestination(){const user=$("username").value.trim();const host=$("computer").value.trim();$("target").value=user+"@"+host;if(!$("target-home").dataset.custom)$("target-home").value=user?"/Users/"+user:"";}
$("username").oninput=manualEdit;$("computer").oninput=manualEdit;$("target-home").oninput=()=>{$("target-home").dataset.custom="true";manualEdit()};$("identity").oninput=manualEdit;
function folderSummary(){$("folder-summary").textContent=roots().length?roots().length+" project folder"+(roots().length===1?"":"s")+" selected.":"No project folders selected.";}
$("workspaces").oninput=folderSummary;
function showStep(next){step=next;for(let n=1;n<=3;n++)$("step-"+n).hidden=n!==step;$("step-progress").textContent="Step "+step+" of 3 · "+["Your new Mac","What to move","Review"][step-1];$("step-"+step).querySelector("h2").focus();}
function connectionValid(){if(connectionBlocked){$("error").textContent="This saved connection is not ready. Start a fresh connection or explicitly configure existing SSH in Advanced setup.";showStep(1);return false}syncDestination();for(const id of ["computer","username","target-home"]){if(!$(id).checkValidity()){showStep(1);$("manual-connection").open=true;$(id).closest("details")?.setAttribute("open","");$(id).reportValidity();return false}}return true;}
$("next-1").onclick=()=>{if(connectionValid())showStep(2)};$("back-2").onclick=()=>showStep(1);$("back-3").onclick=()=>showStep(2);
$("next-2").onclick=()=>{const skills=$("mode").value==="skills";$("review").replaceChildren();for(const [label,value] of [["New Mac",$("target").value],["Moving",skills?"Selected custom skills":"Codex conversations, settings and skills"],["Project folders",String(roots().length)]]){const dt=document.createElement("dt"),dd=document.createElement("dd");dt.textContent=label;dd.textContent=value;$("review").append(dt,dd)}$("replacement-note").textContent=skills?"Matching destination skills are backed up and replaced. Other skills, conversations and projects are kept.":"This replaces selected destination data; it does not merge separate work. Keep your old Mac intact.";showStep(3)};
function modeChanged(){const skills=$("mode").value==="skills";$("key-help").textContent=skills?"Selecting an SSH key does not add it to the migration, and the selection is not saved. Only selected skill contents are copied; review them for private files. Protected SSH and Codex login files are rejected.":fullKeyHelp;$("skill-components").hidden=!skills;$("workspace-label").textContent=skills?"Project folders to search for workspace skills, one per line":"Workspace folders on this Mac, one per line";$("scope-help").textContent=skills?"These folders are searched only when Workspace skills is checked. Only discovered .agents/skills directories are copied, not the whole project. Personal skills need no project-folder selection. Skill contents can include private files; review the discovered list before transfer.":fullScopeHelp;}
$("mode").onchange=modeChanged;
async function api(path,body){const r=await fetch(path,{method:body?"POST":"GET",headers:{"X-Codex-Migrate-Token":token,"Content-Type":"application/json"},...(body?{body:JSON.stringify(body)}:{})});const result=await r.json();if(!r.ok)throw Error(result.error||"The request failed");return result}
async function loadOverview(){
  try{
    const [summary,schedule,backup]=await Promise.all([
      api("/api/vault/summary"),api("/api/vault/schedule"),api("/api/vault/backup-status")
    ]);
    const conversations=(summary.active_transcripts||0)+(summary.archived_transcripts||0);
    const label=`${conversations.toLocaleString()} ${conversations===1?"conversation":"conversations"}`;
    const verifiedScheduled=schedule.enabled&&schedule.healthy&&schedule.last_run?.status==="completed";
    const attention=schedule.last_run?.status==="needs_attention"||backup.status==="needs_attention";
    $("overview-health-card").classList.toggle("attention",!verifiedScheduled||attention);
    $("overview-health-icon").textContent=verifiedScheduled&&!attention?"✓":"!";
    if(attention){
      $("overview-health").textContent="Conversation backup needs review";
      $("overview-health-detail").textContent="An earlier verified version may hold missing content.";
    }else if(verifiedScheduled){
      $("overview-health").textContent="Automatic backup verified";
      $("overview-health-detail").textContent=`${label} · Daily encrypted backup`;
    }else if(schedule.enabled){
      $("overview-health").textContent="First scheduled backup pending";
      $("overview-health-detail").textContent=`${label} · Initial snapshot alone is not scheduled protection`;
    }else if(backup.status==="completed"){
      $("overview-health").textContent="Snapshot verified";
      $("overview-health-detail").textContent=`${label} · Automatic backup is off`;
    }else{
      $("overview-health").textContent="Backup protection is not set up";
      $("overview-health-detail").textContent=`${label} found on this Mac`;
    }
  }catch(error){
    $("overview-health-card").classList.add("attention");
    $("overview-health-icon").textContent="!";
    $("overview-health").textContent="Protection status unavailable";
    $("overview-health-detail").textContent="Open Backups to check this Mac without changing anything.";
  }
}
function receiverView(receiving){$("receiver").hidden=!receiving;$("setup").hidden=receiving;$("step-progress").hidden=receiving;$("receiver-toggle").textContent=receiving?"Back to the old Mac setup":"I’m on the new Mac";}
$("receiver-toggle").onclick=()=>{const receiving=$("receiver").hidden;receiverView(receiving);if(receiving)$("receiver").querySelector("h2").focus();else showStep(step)};
function selectPaired(r){const split=r.target.lastIndexOf("@");$("username").value=r.target.slice(0,split);$("computer").value=r.target.slice(split+1);$("target").value=r.target;$("target-home").value=r.target_home;$("target-home").dataset.custom="true";$("identity").value="";paired=true;connectionBlocked=false;pairingView();$("manual-connection").open=false;}
async function connectionAction(button,action,payload,done){
  if(button.disabled)return;
  const hadFocus=document.activeElement===button;let nextFocus=button;
  button.disabled=true;$("error").textContent="";
  try{nextFocus=done(await api("/api/connection/"+action,payload))||button}
  catch(e){$("error").textContent=e.message}
  finally{button.disabled=false;if(hadFocus&&(document.activeElement===document.body||document.activeElement===button)&&nextFocus.getClientRects().length)nextFocus.focus()}
}
$("create-card").onclick=()=>connectionAction($("create-card"),"request",{},r=>{$("source-card").value=r.card;$("request-area").hidden=false;$("create-card").hidden=true;return $("copy-request")});
$("approve-card").onclick=()=>connectionAction($("approve-card"),"approve",{card:$("request-card").value,apply:true},r=>{$("reply-card").value=r.card;$("reply-area").hidden=false;$("receiver-request-area").hidden=true;return $("copy-reply")});
$("accept-card").onclick=()=>connectionAction($("accept-card"),"accept",{card:$("accepted-card").value,apply:true},r=>{selectPaired(r);return $("next-1")});
$("revoke-pair").onclick=()=>{if(confirm("Remove this old Mac’s SSH access? Wait until migration and recovery have finished."))connectionAction($("revoke-pair"),"revoke",{apply:true},r=>{$("message").textContent=r.message;$("reply-area").hidden=true;$("reply-card").value="";$("receiver-request-area").hidden=false})};
$("restart-pair").onclick=()=>{if(confirm("Start a new connection? Previous local files will be kept. Remove the old access on the new Mac before approving another card."))connectionAction($("restart-pair"),"restart",{apply:true},r=>{paired=false;connectionBlocked=false;pairingView();$("request-area").hidden=true;$("create-card").hidden=false;$("target").value="";$("username").value="";$("computer").value="";$("target-home").value="";$("source-card").value="";$("accepted-card").value="";$("message").textContent=r.message})};
async function copyCard(id){try{await navigator.clipboard.writeText($(id).value);$("message").textContent="Copied. Paste it into Codex Migrate on your other Mac."}catch(e){$(id).closest("details").open=true;$(id).focus();$(id).select();$("message").textContent="Card selected. Press Command-C to copy."}}
$("copy-request").onclick=()=>copyCard("source-card");$("copy-reply").onclick=()=>copyCard("reply-card");
function attached(){ $("receiver-toggle").hidden=true;$("receiver").hidden=true; $("attached").hidden=false;$("setup").hidden=true;$("step-progress").hidden=true;$("continue").href="/migration#token="+encodeURIComponent(token);$("message").textContent="The helper is ready. No transfer was started automatically."; }
function restoreConnection(s,c){
  const source=s.connection?.source, receiver=s.connection?.receiver;
  if(source?.status==="request_ready"){$("source-card").value=source.card;$("request-area").hidden=false;$("create-card").hidden=true;}
  if(source?.status==="paired"&&(!c.target||c.paired))selectPaired(source);
  if(receiver){
    if(!source&&!c.target)receiverView(true);
    if(receiver.status==="approved"){$("reply-card").value=receiver.card;$("reply-area").hidden=false;$("receiver-request-area").hidden=true;}
    if(receiver.status==="approval_pending"){$("request-card").value=receiver.request_card;$("message").textContent="Connection approval was interrupted or access is missing. Review and approve again to restore access; nothing resumed automatically.";}
    if(receiver.status==="expired")$("message").textContent="This connection expired. Remove its old access, then approve a fresh card from the old Mac.";
  }
  if(s.connection_error||source?.status==="expired"||(c.paired&&source?.status!=="paired")){
    connectionBlocked=!!c.paired||!!source||!c.target;paired=false;pairingView();
    $("error").textContent=s.connection_error||"The saved connection is missing or expired. Start a fresh connection; previous files are kept.";
  }
}
async function load(){try{
  const s=await api("/api/setup");if(s.attached){attached();return}
  const c=s.saved||{};$("target").value=c.target||"";const split=(c.target||"").lastIndexOf("@");
  $("username").value=split>=0?c.target.slice(0,split):"";$("computer").value=split>=0?c.target.slice(split+1):"";
  $("target-home").value=c.target_home||"";
  if(c.target_home&&c.target_home!=="/Users/"+$("username").value)$("target-home").dataset.custom="true";else delete $("target-home").dataset.custom;
  $("workspaces").value=(c.workspace_roots||[]).join("\n");$("mode").value=c.mode||"full";
  $("personal-skills").checked=!c.components||c.components.includes("personal-skills");$("workspace-skills").checked=(c.components||[]).includes("workspace-skills");
  paired=!!c.paired;pairingView();modeChanged();folderSummary();$("apply").checked=false;$("fields").disabled=false;
  $("message").textContent=s.saved?"Restored your last setup. Review it before continuing; changes remain disabled.":"";
  restoreConnection(s,c);
}catch(e){$("error").textContent=e.message+". Reopen the browser from the local helper if its token is missing."}}
async function folders(path){
  if($("folders").disabled||$("suggest").disabled)return;
  const button=$(path==="/api/folders"?"folders":"suggest"),hadFocus=document.activeElement===button;
  for(const id of ["folders","suggest","next-2"])$(id).disabled=true;
  $("error").textContent="";
  $("message").textContent="";$("folder-error").textContent="";
  $("folder-message").textContent=path==="/api/folders"?"Choose folders in the macOS dialog, then return here.":"Looking for common project folders…";
  try{const r=await api(path,{});$("workspaces").value=[...new Set([...roots(),...r.paths])].join("\n");folderSummary();$("folder-message").textContent=r.message}
  catch(e){$("folder-error").textContent=e.message;$("folder-message").textContent=""}
  finally{
    for(const id of ["folders","suggest","next-2"])$(id).disabled=false;
    if(hadFocus&&(document.activeElement===document.body||document.activeElement===button)&&button.getClientRects().length)button.focus();
  }
}
$("folders").onclick=()=>folders("/api/folders");$("suggest").onclick=()=>folders("/api/suggestions");
$("setup").onsubmit=async e=>{e.preventDefault();if(step<3){$(step===1?"next-1":"next-2").click();return}if(!connectionValid())return;$("open").disabled=true;$("error").textContent="";try{await api("/api/setup",{target:$("target").value.trim(),target_home:$("target-home").value.trim(),workspace_roots:roots(),identity_file:$("identity").value.trim(),apply:$("apply").checked,paired,mode:$("mode").value,components:$("mode").value==="skills"?["personal-skills","workspace-skills"].filter(id=>$(id).checked):[]});location.href="/migration#token="+encodeURIComponent(token)}catch(e){$("error").textContent=e.message;$("open").disabled=false}};
load();
loadOverview();
</script>
</body>
</html>'''
SETUP_HTML = with_support(SETUP_HTML)
SETUP_HTML = SETUP_HTML.replace(
    SUPPORT_HTML,
    '<details id="setup-help"><summary>Help and diagnostic report</summary>'
    + SUPPORT_HTML + '</details>',
)
SETUP_HTML = SETUP_HTML.replace('href="#migration-help"', 'href="#setup-help"')
SETUP_HTML = SETUP_HTML.replace('</body>', '''<script>
document.querySelector('.support-link').addEventListener('click',()=>{
  document.getElementById('setup-help').open=true;
});
</script>
</body>''')


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
        self._vault_lock = threading.Lock()
        self._vault_thread = None
        self._vault_status = {"status": "idle"}
        self._restore_thread = None
        self._restore_status = {"status": "idle"}
        self._install_thread = None
        self._install_status = {"status": "idle"}
        self._browse_thread = None
        self._browse_status = {"status": "idle"}
        self._browse_temporary = None
        self._browse_home = None
        self._browse_catalog = None
        self._browse_data_lock = threading.RLock()
        self._export_ticket_lock = threading.Lock()
        self._export_tickets = {}
        self._thread_install_thread = None
        self._thread_install_status = {"status": "idle"}
        self._closing = False
        self.pairing = Pairing(self.source_home, self.registry.root)

    def configure(self, payload):
        with self._setup_lock:
            if self.engine is not None:
                raise MigrationError("A migration is already configured. Restart the helper to change scope.")
            allowed = {"target", "target_home", "workspace_roots", "identity_file", "apply", "mode", "components", "paired"}
            if not isinstance(payload, dict) or set(payload) - allowed:
                raise MigrationError("Unexpected setup fields")
            if not isinstance(payload.get("apply", False), bool):
                raise MigrationError("Enable changes must be true or false")
            if not isinstance(payload.get("paired", False), bool):
                raise MigrationError("Invalid paired connection choice")
            if payload.get("paired") and payload.get("identity_file"):
                raise MigrationError("Paired connections use their own key, not a custom key path")
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
            if payload.get("paired"):
                from dataclasses import replace
                config = replace(config, ssh=self.pairing.options(config.target, config.target_home)).validate()
            saved = {"target": config.target, "target_home": config.target_home,
                     "workspace_roots": sorted(config.workspace_roots)}
            if payload.get("paired"):
                saved["paired"] = True
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
        with self._vault_lock:
            vault_idle = (
                not (self._vault_thread and self._vault_thread.is_alive())
                and not (self._restore_thread and self._restore_thread.is_alive())
                and not (self._install_thread and self._install_thread.is_alive())
                and not (self._browse_thread and self._browse_thread.is_alive())
                and not (self._thread_install_thread
                         and self._thread_install_thread.is_alive())
                and not self._vault_status.get("recovery_key")
            )
        return vault_idle and (self.engine is None or (
            self.state.read().get("status") not in ("running", "paused")
            and not (self.engine._thread and self.engine._thread.is_alive())))

    def close(self):
        if self.engine is not None:
            self.engine.shutdown()
            self.state.release_process_lock()
        with self._browse_data_lock:
            if self._browse_temporary is not None:
                self._browse_temporary.cleanup()
                self._browse_temporary = None
                self._browse_home = None
                self._browse_catalog = None
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

    def choose_vault_folder(self):
        if platform.system() != "Darwin":
            raise MigrationError("Native folder selection requires macOS")
        if not self._picker_lock.acquire(blocking=False):
            raise MigrationError("A folder picker is already open")
        try:
            result = subprocess.run(["/usr/bin/osascript", "-l", "JavaScript", "-e", '''
const app = Application.currentApplication();
app.includeStandardAdditions = true;
String(app.chooseFolder({withPrompt: "Choose an empty folder or an existing Codex Vault"}));
'''], capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                if "(-128)" in result.stderr:
                    return None
                raise MigrationError("Vault folder picker could not open")
            path = result.stdout.strip()
            if not path or "\n" in path or "\r" in path:
                raise MigrationError("The selected Vault folder is invalid")
            return path
        finally:
            self._picker_lock.release()

    def choose_restore_folder(self):
        if platform.system() != "Darwin":
            raise MigrationError("Native folder selection requires macOS")
        if not self._picker_lock.acquire(blocking=False):
            raise MigrationError("A folder picker is already open")
        try:
            result = subprocess.run(["/usr/bin/osascript", "-l", "JavaScript", "-e", '''
const app = Application.currentApplication();
app.includeStandardAdditions = true;
String(app.chooseFolder({withPrompt: "Choose an empty folder for the recovered Codex history"}));
'''], capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                if "(-128)" in result.stderr:
                    return None
                raise MigrationError("Recovery folder picker could not open")
            path = result.stdout.strip()
            if not path or "\n" in path or "\r" in path:
                raise MigrationError("The selected recovery folder is invalid")
            return path
        finally:
            self._picker_lock.release()

    def vault_status(self):
        with self._vault_lock:
            return dict(self._vault_status)

    def vault_schedule(self):
        result = vault_schedule_status(self.source_home)
        if result.get("vault"):
            result["storage"] = self.vault_storage(result["vault"])
        return result

    def vault_storage(self, path):
        if not isinstance(path, str) or not path or len(path) > 4096:
            raise MigrationError("Choose a valid Vault folder")
        return classify_vault_storage(path, self.source_home).as_dict()

    def enable_vault_schedule(self, destination, interval_hours):
        if not isinstance(destination, str) or len(destination) > 4096:
            raise MigrationError("Choose a valid existing Vault folder")
        if isinstance(interval_hours, bool) or not isinstance(interval_hours, int):
            raise MigrationError("Choose a valid backup interval")
        result = install_vault_schedule(
            self.source_home, destination, interval_hours=interval_hours)
        return {"enabled": True, "healthy": True, **result.as_dict()}

    def disable_vault_schedule(self):
        return remove_vault_schedule(self.source_home)

    def vault_restore_status(self):
        with self._vault_lock:
            return dict(self._restore_status)

    def vault_install_status(self):
        with self._vault_lock:
            current = dict(self._install_status)
        if current.get("status") != "idle":
            return current
        return persistent_install_status(self.source_home)

    def vault_snapshots(self, vault):
        if not isinstance(vault, str) or len(vault) > 4096:
            raise MigrationError("Choose a valid existing Vault folder")
        return {"snapshots": [
            item.as_dict() for item in list_vault_snapshots(vault, limit=1000)
        ]}

    @staticmethod
    def _vault_snapshot(snapshot):
        if not isinstance(snapshot, str) or len(snapshot) > 64:
            raise MigrationError("Choose a valid Vault snapshot")
        if snapshot == "latest":
            return snapshot
        try:
            return str(uuid.UUID(snapshot)).lower()
        except (ValueError, TypeError, AttributeError):
            raise MigrationError("Choose a valid Vault snapshot") from None

    def vault_browse_status(self):
        with self._vault_lock:
            return dict(self._browse_status)

    def start_vault_browse(self, vault, snapshot):
        if not isinstance(vault, str) or len(vault) > 4096:
            raise MigrationError("Choose a valid existing Vault folder")
        snapshot = self._vault_snapshot(snapshot)
        temporary = tempfile.TemporaryDirectory(
            prefix=".codex-vault-browser-", dir=self.source_home)
        browse_home = Path(temporary.name)

        def run():
            try:
                result = restore_vault_snapshot(
                    self.source_home, vault, str(browse_home / ".codex"),
                    snapshot=snapshot,
                )
                catalog = snapshot_catalog(vault, snapshot=result.snapshot_id)
                with self._browse_data_lock:
                    old = self._browse_temporary
                    self._browse_temporary = temporary
                    self._browse_home = browse_home
                    self._browse_catalog = catalog
                    if old is not None:
                        old.cleanup()
                with self._vault_lock:
                    self._browse_status = {"status": "ready", **result.as_dict()}
            except Exception:
                temporary.cleanup()
                with self._vault_lock:
                    self._browse_status = {
                        "status": "failed",
                        "error": "The selected backup could not be opened safely. "
                                 "Local Codex history and the encrypted Vault were not changed.",
                    }

        worker = threading.Thread(target=run, daemon=True)
        with self._vault_lock:
            if self._vault_thread and self._vault_thread.is_alive():
                temporary.cleanup()
                raise MigrationError("Wait for the encrypted backup to finish before opening one")
            if self._restore_thread and self._restore_thread.is_alive():
                temporary.cleanup()
                raise MigrationError("Wait for Vault recovery to finish before opening a backup")
            if self._install_thread and self._install_thread.is_alive():
                temporary.cleanup()
                raise MigrationError("Wait for Vault installation to finish before opening a backup")
            if self._browse_thread and self._browse_thread.is_alive():
                temporary.cleanup()
                raise MigrationError("A Vault backup is already being opened")
            if self._thread_install_thread and self._thread_install_thread.is_alive():
                temporary.cleanup()
                raise MigrationError("Wait for selected recovery to finish before opening a backup")
            if self._vault_status.get("recovery_key"):
                temporary.cleanup()
                raise MigrationError("Save and acknowledge the recovery key before opening a backup")
            self._browse_status = {
                "status": "running", "vault": vault, "snapshot": snapshot,
            }
            self._browse_thread = worker
            worker.start()
        return self.vault_browse_status()

    def _browse(self, function, *args):
        with self._browse_data_lock:
            if self._browse_home is None:
                raise MigrationError("Open a verified Vault backup before searching it")
            return function(str(self._browse_home), *args)

    def search_vault_backup(self, phrase, limit, offset=0):
        with self._browse_data_lock:
            if self._browse_home is None or self._browse_catalog is None:
                raise MigrationError("Open a verified Vault backup before searching it")
            return search_vault(str(self._browse_home), phrase, limit,
                                catalog=self._browse_catalog, offset=offset)

    def read_vault_backup_thread(self, collection, transcript):
        return self._browse(read_thread, collection, transcript)

    def read_vault_backup_thread_page(self, collection, transcript, cursor):
        return self._browse(read_thread_page, collection, transcript, cursor)

    def issue_vault_export_ticket(self, collection, transcript, source="backup"):
        if collection not in ("active", "archived") or not isinstance(transcript, str) \
                or not transcript or len(transcript) > 4096 or source not in ("backup", "local"):
            raise MigrationError("Choose an opened conversation to export")
        with self._browse_data_lock if source == "backup" else nullcontext():
            if source == "backup" and self._browse_home is None:
                raise MigrationError("Open a verified Vault backup before exporting it")
            export_home = str(self._browse_home) if source == "backup" else str(self.source_home)
            _find_transcript(export_home, collection, transcript)
            expected_bytes = sum(len(chunk) for chunk in markdown_chunks(
                export_home, collection, transcript))
        ticket = secrets.token_urlsafe(32)
        with self._export_ticket_lock:
            now = time.monotonic()
            self._export_tickets = {key: value for key, value in self._export_tickets.items()
                                    if value[0] > now}
            if len(self._export_tickets) >= 16:
                raise MigrationError("Too many pending exports. Retry in one minute.")
            self._export_tickets[ticket] = (now + 60, source, export_home,
                                            collection, transcript, expected_bytes)
        return ticket

    def consume_vault_export_ticket(self, ticket):
        with self._export_ticket_lock:
            value = self._export_tickets.pop(ticket, None)
        if value is None or value[0] <= time.monotonic():
            raise MigrationError("This download link expired. Choose Download Markdown again.")
        return value[1:]

    def vault_thread_install_status(self):
        with self._vault_lock:
            return dict(self._thread_install_status)

    def start_vault_thread_install(self, collection, transcript):
        if collection not in ("active", "archived"):
            raise MigrationError("Choose a valid conversation")
        if not isinstance(transcript, str) or len(transcript) > 4096:
            raise MigrationError("Choose a valid conversation")
        with self._vault_lock:
            if self._browse_status.get("status") != "ready":
                raise MigrationError("Open a verified Vault backup before recovering a conversation")
            vault = self._browse_status.get("vault")
            snapshot = self._browse_status.get("snapshot_id")
        if not isinstance(vault, str) or not isinstance(snapshot, str):
            raise MigrationError("Open a verified Vault backup before recovering a conversation")

        def run():
            try:
                result = install_vault_thread(
                    self.source_home, vault, collection, transcript,
                    snapshot=snapshot,
                )
                with self._vault_lock:
                    self._thread_install_status = {
                        "status": result.status, **result.as_dict(),
                    }
            except MigrationError as error:
                needs_attention = str(error).startswith(
                    "Selected recovery stopped and automatic rollback could not be verified.")
                with self._vault_lock:
                    if needs_attention:
                        self._thread_install_status = {
                            "status": "needs_attention",
                            "error": "Selected recovery needs attention. Keep Codex closed and "
                                     "review local conversation history before retrying.",
                        }
                    else:
                        self._thread_install_status = {
                            "status": "failed",
                            "error": "Selected recovery stopped safely. No existing Codex "
                                     "conversation was replaced or merged.",
                        }
            except Exception:
                with self._vault_lock:
                    self._thread_install_status = {
                        "status": "failed",
                        "error": "Selected recovery could not start safely. No existing Codex "
                                 "conversation was replaced or merged.",
                    }

        worker = threading.Thread(target=run, daemon=True)
        with self._vault_lock:
            if self._vault_thread and self._vault_thread.is_alive():
                raise MigrationError("Wait for the encrypted backup to finish before recovery")
            if self._restore_thread and self._restore_thread.is_alive():
                raise MigrationError("Wait for Vault recovery to finish before selected recovery")
            if self._install_thread and self._install_thread.is_alive():
                raise MigrationError("Wait for Vault installation to finish before selected recovery")
            if self._browse_thread and self._browse_thread.is_alive():
                raise MigrationError("Wait for the backup to finish opening")
            if self._thread_install_thread and self._thread_install_thread.is_alive():
                raise MigrationError("A selected conversation recovery is already running")
            if persistent_install_status(self.source_home).get("status") == "interrupted":
                raise MigrationError("Roll back the interrupted Vault installation before retrying")
            self._thread_install_status = {
                "status": "running", "vault": vault, "snapshot": snapshot,
                "collection": collection, "transcript": transcript,
            }
            self._thread_install_thread = worker
            worker.start()
        return self.vault_thread_install_status()

    def start_vault_restore(self, vault, output, snapshot):
        if not isinstance(vault, str) or len(vault) > 4096:
            raise MigrationError("Choose a valid existing Vault folder")
        if not isinstance(output, str) or len(output) > 4096:
            raise MigrationError("Choose a valid empty recovery folder")
        if not isinstance(snapshot, str) or len(snapshot) > 64:
            raise MigrationError("Choose a valid Vault snapshot")
        if snapshot != "latest":
            try:
                snapshot = str(uuid.UUID(snapshot)).lower()
            except (ValueError, TypeError, AttributeError):
                raise MigrationError("Choose a valid Vault snapshot") from None

        def run():
            try:
                result = restore_vault_snapshot(
                    self.source_home, vault, output, snapshot=snapshot)
                with self._vault_lock:
                    self._restore_status = {"status": "completed", **result.as_dict()}
            except Exception:
                with self._vault_lock:
                    self._restore_status = {
                        "status": "failed",
                        "error": "Recovery stopped safely. Live Codex data and the encrypted Vault were not changed.",
                    }

        worker = threading.Thread(target=run, daemon=True)
        with self._vault_lock:
            if self._vault_thread and self._vault_thread.is_alive():
                raise MigrationError("Wait for the encrypted backup to finish before recovering")
            if self._restore_thread and self._restore_thread.is_alive():
                raise MigrationError("A Vault recovery is already running")
            if self._install_thread and self._install_thread.is_alive():
                raise MigrationError("Wait for Vault installation to finish before recovering")
            if self._vault_status.get("recovery_key"):
                raise MigrationError("Save and acknowledge the recovery key before recovering")
            self._restore_status = {
                "status": "running", "vault": vault, "output": output,
                "snapshot": snapshot,
            }
            self._restore_thread = worker
            worker.start()
        return self.vault_restore_status()

    def start_vault_install(self, vault, snapshot):
        if not isinstance(vault, str) or len(vault) > 4096:
            raise MigrationError("Choose a valid existing Vault folder")
        if not isinstance(snapshot, str) or len(snapshot) > 64:
            raise MigrationError("Choose a valid Vault snapshot")
        if snapshot != "latest":
            try:
                snapshot = str(uuid.UUID(snapshot)).lower()
            except (ValueError, TypeError, AttributeError):
                raise MigrationError("Choose a valid Vault snapshot") from None

        def run():
            try:
                result = install_vault_snapshot(
                    self.source_home, vault, snapshot=snapshot)
                with self._vault_lock:
                    self._install_status = {"status": "completed", **result.as_dict()}
            except Exception:
                try:
                    status = persistent_install_status(self.source_home)
                except Exception:
                    status = {"status": "interrupted"}
                with self._vault_lock:
                    if status.get("status") == "interrupted":
                        self._install_status = {
                            **status,
                            "error": "Installation was interrupted. Keep Codex closed and roll back before retrying.",
                        }
                    else:
                        self._install_status = {
                            "status": "failed",
                            "error": "Installation stopped safely. Previous history was restored if replacement had begun.",
                        }

        worker = threading.Thread(target=run, daemon=True)
        with self._vault_lock:
            if self._vault_thread and self._vault_thread.is_alive():
                raise MigrationError("Wait for the encrypted backup to finish before installing")
            if self._restore_thread and self._restore_thread.is_alive():
                raise MigrationError("Wait for Vault recovery to finish before installing")
            if self._install_thread and self._install_thread.is_alive():
                raise MigrationError("A Vault installation is already running")
            if self._vault_status.get("recovery_key"):
                raise MigrationError("Save and acknowledge the recovery key before installing")
            if persistent_install_status(self.source_home).get("status") == "interrupted":
                raise MigrationError("Roll back the interrupted Vault installation before retrying")
            self._install_status = {
                "status": "running", "vault": vault, "snapshot": snapshot,
            }
            self._install_thread = worker
            worker.start()
        return self.vault_install_status()

    def start_vault_install_recovery(self):
        def run():
            try:
                result = recover_interrupted_install(self.source_home, apply=True)
                with self._vault_lock:
                    self._install_status = dict(result)
            except Exception:
                with self._vault_lock:
                    self._install_status = {
                        "status": "interrupted",
                        "error": "Rollback could not be verified. Keep Codex closed and contact support.",
                    }

        worker = threading.Thread(target=run, daemon=True)
        with self._vault_lock:
            if self._vault_thread and self._vault_thread.is_alive():
                raise MigrationError("Wait for the encrypted backup to finish before rollback")
            if self._restore_thread and self._restore_thread.is_alive():
                raise MigrationError("Wait for Vault recovery to finish before rollback")
            if self._install_thread and self._install_thread.is_alive():
                raise MigrationError("A Vault installation operation is already running")
            if persistent_install_status(self.source_home).get("status") != "interrupted":
                raise MigrationError("No interrupted Vault installation needs rollback")
            self._install_status = {"status": "rolling_back"}
            self._install_thread = worker
            worker.start()
        return self.vault_install_status()

    def acknowledge_vault_recovery_key(self):
        with self._vault_lock:
            if not self._vault_status.get("recovery_key"):
                raise MigrationError("No Vault recovery key needs acknowledgement")
            self._vault_status.pop("recovery_key", None)
            return dict(self._vault_status)

    def start_vault_backup(self, destination):
        if not isinstance(destination, str) or len(destination) > 4096:
            raise MigrationError("Choose a valid Vault folder")
        # Reject conflicting work before inspecting source data. The check is
        # repeated at admission below because planning deliberately runs
        # outside the status lock.
        with self._vault_lock:
            if self._restore_thread and self._restore_thread.is_alive():
                raise MigrationError("Wait for Vault recovery to finish before backing up")
            if self._install_thread and self._install_thread.is_alive():
                raise MigrationError("Wait for Vault installation to finish before backing up")
        storage = self.vault_storage(destination)
        planned = plan_vault_backup(self.source_home, destination)

        def progress(completed_files, total_files, completed_bytes, total_bytes):
            with self._vault_lock:
                if self._vault_status.get("status") == "running":
                    self._vault_status.update(
                        completed_files=completed_files, total_files=total_files,
                        completed_bytes=completed_bytes, total_bytes=total_bytes)

        def run():
            try:
                result = backup_vault(
                    self.source_home, planned.destination, progress=progress)
                with self._vault_lock:
                    self._vault_status = {
                        "status": "needs_attention" if result.needs_attention else "completed",
                        "storage": storage,
                        **result.as_dict(),
                    }
            except Exception:
                # A first backup can fail after its new Keychain key and Vault
                # metadata are durable but before a verified snapshot exists.
                # Recover that key for the customer instead of making the only
                # portable copy disappear with this process.
                recovery_key = None
                try:
                    recovery_key = export_recovery_key(planned.destination)
                except Exception:
                    pass
                with self._vault_lock:
                    self._vault_status = {
                        "status": "failed",
                        "destination": planned.destination,
                        "storage": storage,
                        "error": "Encrypted backup stopped safely. The previous verified snapshot and local Codex data were not changed.",
                    }
                    if recovery_key:
                        self._vault_status["recovery_key"] = recovery_key

        worker = threading.Thread(target=run, daemon=True)
        # Publish and start the worker while holding the same lock used by the
        # admission check. Concurrent browser requests cannot both launch a
        # writer into the same repository.
        with self._vault_lock:
            if self._vault_thread and self._vault_thread.is_alive():
                raise MigrationError("An encrypted backup is already running")
            if self._restore_thread and self._restore_thread.is_alive():
                raise MigrationError("Wait for Vault recovery to finish before backing up")
            if self._install_thread and self._install_thread.is_alive():
                raise MigrationError("Wait for Vault installation to finish before backing up")
            if self._vault_status.get("recovery_key"):
                raise MigrationError("Save and acknowledge the recovery key before another backup")
            self._vault_status = {
                "status": "running",
                "destination": planned.destination,
                "storage": storage,
                "completed_files": 0,
                "total_files": planned.transcript_files,
                "completed_bytes": 0,
                "total_bytes": planned.transcript_bytes,
            }
            self._vault_thread = worker
            worker.start()
        return self.vault_status()

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
                parsed = urlsplit(self.path)
                if parsed.path == "/vault":
                    self._html(VAULT_HTML)
                    return
                if parsed.path == "/api/vault/download":
                    query = parse_qs(parsed.query)
                    if set(query) != {"ticket"} or len(query["ticket"]) != 1 \
                            or len(query["ticket"][0]) > 128:
                        self._json(400, {"error": "Invalid download link"})
                        return
                    stream_started = False
                    try:
                        source, export_home, collection, transcript, expected_bytes = setup.consume_vault_export_ticket(
                            query["ticket"][0])
                        with setup._browse_data_lock if source == "backup" else nullcontext():
                            if source == "backup" and (setup._browse_home is None or
                                                       str(setup._browse_home) != export_home):
                                raise MigrationError("The opened backup changed before export")
                            if source == "local" and export_home != str(setup.source_home):
                                raise MigrationError("The local source changed before export")
                            chunks = markdown_chunks(export_home, collection, transcript)
                            first = next(chunks)
                            self.send_response(200)
                            self.send_header("Content-Type", "text/markdown; charset=utf-8")
                            self.send_header("Content-Disposition", 'attachment; filename="codex-conversation.md"')
                            self.send_header("Content-Length", str(expected_bytes))
                            self.send_header("Cache-Control", "no-store")
                            self.send_header("X-Content-Type-Options", "nosniff")
                            self.send_header("Referrer-Policy", "no-referrer")
                            self.send_header("Connection", "close")
                            self.end_headers()
                            stream_started = True
                            written = len(first)
                            self.wfile.write(first)
                            for chunk in chunks:
                                written += len(chunk)
                                if written > expected_bytes:
                                    raise MigrationError("The saved conversation changed during export")
                                self.wfile.write(chunk)
                            if written != expected_bytes:
                                raise MigrationError("The saved conversation changed during export")
                            self.close_connection = True
                    except MigrationError:
                        if stream_started:
                            self.close_connection = True
                        else:
                            self._json(409, {"error": "The selected backup could not be exported safely."})
                    except (BrokenPipeError, ConnectionResetError):
                        self.close_connection = True
                    return
                if parsed.path.startswith("/api/vault/"):
                    if not self._authorized():
                        self._json(403, {"error": "Missing or invalid local control token"})
                        return
                    try:
                        query = parse_qs(parsed.query, keep_blank_values=True)
                        if parsed.path == "/api/vault/summary" and not query:
                            self._json(200, inspect_vault(setup.source_home).as_dict())
                            return
                        if parsed.path == "/api/vault/backup-status" and not query:
                            self._json(200, setup.vault_status())
                            return
                        if parsed.path == "/api/vault/schedule" and not query:
                            self._json(200, setup.vault_schedule())
                            return
                        if (parsed.path == "/api/vault/storage"
                                and set(query) == {"path"}
                                and len(query["path"]) == 1):
                            self._json(200, setup.vault_storage(query["path"][0]))
                            return
                        if parsed.path == "/api/vault/restore-status" and not query:
                            self._json(200, setup.vault_restore_status())
                            return
                        if parsed.path == "/api/vault/install-status" and not query:
                            self._json(200, setup.vault_install_status())
                            return
                        if parsed.path == "/api/vault/browse-status" and not query:
                            self._json(200, setup.vault_browse_status())
                            return
                        if parsed.path == "/api/vault/thread-install-status" and not query:
                            self._json(200, setup.vault_thread_install_status())
                            return
                        if (parsed.path == "/api/vault/snapshots"
                                and set(query) == {"vault"} and len(query["vault"]) == 1):
                            self._json(200, setup.vault_snapshots(query["vault"][0]))
                            return
                        if (parsed.path == "/api/vault/history-search"
                                and set(query) == {"vault", "q"}
                                and all(len(value) == 1 for value in query.values())):
                            vault, phrase = query["vault"][0], query["q"][0]
                            if len(vault) > 4096 or len(phrase) > 500:
                                raise ValueError("invalid Vault history search")
                            self._json(200, {"results": search_titles(vault, phrase)})
                            return
                        if (parsed.path == "/api/vault/thread-history"
                                and set(query) == {"vault", "key"}
                                and all(len(value) == 1 for value in query.values())):
                            vault, key = query["vault"][0], query["key"][0]
                            if len(vault) > 4096 or len(key) > 4096:
                                raise ValueError("invalid Vault thread history")
                            self._json(200, {"versions": thread_timeline(vault, key)})
                            return
                        if parsed.path == "/api/vault/search" and set(query) <= {"q", "limit", "source", "offset"}:
                            phrase = query.get("q", [""])[0]
                            raw_limit = query.get("limit", ["50"])[0]
                            raw_offset = query.get("offset", ["0"])[0]
                            source = query.get("source", ["local"])[0]
                            if (len(phrase) > 500 or len(raw_limit) > 4
                                    or len(raw_offset) > 6
                                    or source not in ("local", "backup")):
                                raise ValueError("invalid history search")
                            page_size = int(raw_limit)
                            if not 1 <= page_size <= 499:
                                raise ValueError("invalid history search page size")
                            offset = int(raw_offset)
                            results = (setup.search_vault_backup(phrase, page_size + 1, offset)
                                       if source == "backup" else
                                       search_vault(setup.source_home, phrase, page_size + 1,
                                                    offset=offset))
                            self._json(200, {"results": [item.as_dict() for item in results[:page_size]],
                                             "has_more": len(results) > page_size})
                            return
                        if (parsed.path in ("/api/vault/thread", "/api/vault/export")
                                and set(query) <= {"collection", "transcript", "source", "cursor"}):
                            collection = query.get("collection", [""])[0]
                            transcript = query.get("transcript", [""])[0]
                            source = query.get("source", ["local"])[0]
                            if (len(collection) > 16 or len(transcript) > 4096
                                    or source not in ("local", "backup")
                                    or ("cursor" in query and (parsed.path != "/api/vault/thread"
                                        or len(query["cursor"]) != 1
                                        or len(query["cursor"][0]) > 20))):
                                raise ValueError("invalid conversation identifier")
                            if parsed.path == "/api/vault/thread":
                                cursor = int(query.get("cursor", ["0"])[0])
                                thread, next_cursor = (
                                    setup.read_vault_backup_thread_page(collection, transcript, cursor)
                                    if source == "backup" else
                                    read_thread_page(setup.source_home, collection, transcript, cursor))
                                self._json(200, {**thread.as_dict(),
                                                 "next_cursor": next_cursor})
                                return
                            thread = (setup.read_vault_backup_thread(collection, transcript)
                                      if source == "backup" else
                                      read_thread(setup.source_home, collection, transcript))
                            if parsed.path == "/api/vault/thread":
                                self._json(200, thread.as_dict())
                            else:
                                encoded = vault_markdown(thread).encode("utf-8")
                                self.send_response(200)
                                self.send_header("Content-Type", "text/markdown; charset=utf-8")
                                self.send_header("Content-Disposition", 'attachment; filename="codex-conversation.md"')
                                self.send_header("Cache-Control", "no-store")
                                self.send_header("X-Content-Type-Options", "nosniff")
                                self.send_header("Referrer-Policy", "no-referrer")
                                self.send_header("Content-Length", str(len(encoded)))
                                self.end_headers()
                                self.wfile.write(encoded)
                            return
                        self._json(404, {"error": "Not found"})
                    except (MigrationError, ValueError):
                        self._json(400, {"error": "Local Codex history could not be read safely. The original files were not changed."})
                    except Exception:
                        self._json(409, {"error": "Local Codex history is unavailable. The original files were not changed."})
                    return
                if self.path == "/api/setup":
                    if not self._authorized():
                        self._json(403, {"error": "Missing or invalid local control token"})
                        return
                    result = {"saved": setup.registry.read().get("saved"),
                              "attached": setup.engine is not None}
                    if setup.engine is None:
                        with setup._request_lock:
                            try:
                                result["connection"] = setup.pairing.snapshot()
                            except MigrationError as exc:
                                result["connection_error"] = str(exc)
                            except Exception:
                                result["connection_error"] = "Saved connection could not be verified. Files were kept; use connection recovery or contact support."
                    self._json(200, result)
                    return
                if parsed.path == "/":
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
                        self._json(409, {"error": "Finish running work and save any displayed Vault recovery key before quitting."})
                        return
                    setup._closing = True
                    self._json(200, {"closing": True})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                if self.path == "/api/vault/export-ticket":
                    try:
                        length = int(self.headers.get("Content-Length", "0"))
                        if not 0 < length <= 8192:
                            raise MigrationError("Invalid export request size")
                        payload = json.loads(self.rfile.read(length))
                        if (not isinstance(payload, dict) or
                                set(payload) != {"collection", "transcript", "source"}):
                            raise MigrationError("Choose a saved conversation to export")
                        ticket = setup.issue_vault_export_ticket(
                            payload["collection"], payload["transcript"], payload["source"])
                        self._json(200, {"url": "/api/vault/download?ticket=" + ticket})
                    except (MigrationError, ValueError, TypeError):
                        self._json(400, {"error": "The saved conversation could not be prepared for export."})
                    return
                if self.path in ("/api/vault/folder", "/api/vault/backup",
                                 "/api/vault/recovery-saved", "/api/vault/schedule",
                                 "/api/vault/schedule-remove", "/api/vault/restore-folder",
                                 "/api/vault/restore", "/api/vault/install",
                                 "/api/vault/install-recover", "/api/vault/browse",
                                 "/api/vault/install-thread"):
                    try:
                        length = int(self.headers.get("Content-Length", "0"))
                        if not 0 < length <= 8192:
                            raise MigrationError("Invalid Vault request size")
                        payload = json.loads(self.rfile.read(length))
                        if (payload != {} and self.path not in (
                                "/api/vault/backup", "/api/vault/schedule",
                                "/api/vault/schedule-remove", "/api/vault/restore",
                                "/api/vault/install", "/api/vault/install-recover",
                                "/api/vault/browse", "/api/vault/install-thread")):
                            raise MigrationError("Invalid Vault request")
                        if self.path == "/api/vault/folder":
                            path = setup.choose_vault_folder()
                            self._json(200, {
                                "path": path,
                                "storage": setup.vault_storage(path) if path else None,
                            })
                        elif self.path == "/api/vault/restore-folder":
                            path = setup.choose_restore_folder()
                            self._json(200, {"path": path})
                        elif self.path == "/api/vault/recovery-saved":
                            self._json(200, setup.acknowledge_vault_recovery_key())
                        elif self.path == "/api/vault/schedule":
                            if (not isinstance(payload, dict)
                                    or set(payload) != {"destination", "interval_hours", "apply"}
                                    or payload.get("apply") is not True):
                                raise MigrationError("Automatic backup requires explicit confirmation")
                            self._json(200, setup.enable_vault_schedule(
                                payload.get("destination"), payload.get("interval_hours")))
                        elif self.path == "/api/vault/schedule-remove":
                            if payload != {"apply": True}:
                                raise MigrationError("Turning off automatic backup requires explicit confirmation")
                            self._json(200, setup.disable_vault_schedule())
                        elif self.path == "/api/vault/restore":
                            if (not isinstance(payload, dict)
                                    or set(payload) != {"vault", "output", "snapshot", "apply"}
                                    or payload.get("apply") is not True):
                                raise MigrationError("Vault recovery requires explicit confirmation")
                            self._json(202, setup.start_vault_restore(
                                payload.get("vault"), payload.get("output"),
                                payload.get("snapshot")))
                        elif self.path == "/api/vault/install":
                            if (not isinstance(payload, dict)
                                    or set(payload) != {"vault", "snapshot", "apply"}
                                    or payload.get("apply") is not True):
                                raise MigrationError("Vault installation requires explicit confirmation")
                            self._json(202, setup.start_vault_install(
                                payload.get("vault"), payload.get("snapshot")))
                        elif self.path == "/api/vault/browse":
                            if (not isinstance(payload, dict)
                                    or set(payload) != {"vault", "snapshot", "apply"}
                                    or payload.get("apply") is not True):
                                raise MigrationError("Opening a Vault backup requires explicit confirmation")
                            self._json(202, setup.start_vault_browse(
                                payload.get("vault"), payload.get("snapshot")))
                        elif self.path == "/api/vault/install-thread":
                            if (not isinstance(payload, dict)
                                    or set(payload) != {"collection", "transcript", "apply"}
                                    or payload.get("apply") is not True):
                                raise MigrationError("Selected recovery requires explicit confirmation")
                            self._json(202, setup.start_vault_thread_install(
                                payload.get("collection"), payload.get("transcript")))
                        elif self.path == "/api/vault/install-recover":
                            if payload != {"apply": True}:
                                raise MigrationError("Vault rollback requires explicit confirmation")
                            self._json(202, setup.start_vault_install_recovery())
                        else:
                            if (not isinstance(payload, dict)
                                    or set(payload) != {"destination", "apply"}
                                    or payload.get("apply") is not True):
                                raise MigrationError("Encrypted backup requires explicit confirmation")
                            self._json(202, setup.start_vault_backup(payload.get("destination")))
                    except MigrationError as error:
                        self._json(400, {"error": str(error)})
                    except Exception:
                        message = ("Vault recovery could not finish safely."
                                   if self.path.startswith("/api/vault/restore") else
                                   "Vault installation could not finish safely."
                                   if self.path.startswith("/api/vault/install") else
                                   "Encrypted backup setup could not finish safely.")
                        self._json(400, {"error": message})
                    return
                if self.path.startswith("/api/connection/"):
                    if setup.engine is not None:
                        self._json(409, {"error": "Finish or stop the current migration before changing its connection."})
                        return
                    try:
                        length = int(self.headers.get("Content-Length", "0"))
                        if not 0 < length <= 16384:
                            raise MigrationError("Invalid connection request size")
                        payload = json.loads(self.rfile.read(length))
                        if not isinstance(payload, dict) or set(payload) - {"card", "apply"}:
                            raise MigrationError("Invalid connection request")
                        action = self.path.rsplit("/", 1)[-1]
                        if action == "request" and payload == {}:
                            result = setup.pairing.request()
                        elif action == "approve":
                            result = setup.pairing.approve(payload.get("card"), payload.get("apply", False))
                        elif action == "accept":
                            result = setup.pairing.accept(payload.get("card"), payload.get("apply", False))
                        elif action == "revoke":
                            result = setup.pairing.revoke(payload.get("apply", False))
                        elif action == "restart":
                            result = setup.pairing.restart(payload.get("apply", False))
                        else:
                            raise MigrationError("Unknown connection action")
                        self._json(200, result)
                    except MigrationError as error:
                        self._json(400, {"error": str(error)})
                    except Exception:
                        self._json(400, {"error": "Connection setup could not finish. Enable Remote Login on the new Mac, use this account's normal home, and check permissions. No password was requested. Contact support if it continues."})
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
                            if self.path == "/api/folders":
                                try:
                                    paths = setup.choose_folders()
                                except Exception:
                                    # Never expose native stderr or exception text: it may contain private paths.
                                    self._json(400, {"error": FOLDER_PICKER_ERROR})
                                    return
                                message = ("Review the selected folder paths." if paths else
                                           "No folders added. Your existing selection is unchanged.")
                            else:
                                paths = [str(Path(setup.source_home) / name)
                                         for name in ("Git", "Projects", "Developer")
                                         if (Path(setup.source_home) / name).is_dir()]
                                message = "Review the selected folders. Suggestions are not an exhaustive repository scan."
                            self._json(200, {"paths": paths, "message": message})
                    except Exception:
                        # Do not return user-supplied key paths or exception reprs.
                        self._json(400, {"error": "Setup failed. Check the destination, absolute folder paths, permissions, and whether another migration or folder picker is already open."})
                    return
                if setup.engine is None:
                    self._json(409, {"error": "Configure a migration first"})
                    return
                super().do_POST()

        return Handler
