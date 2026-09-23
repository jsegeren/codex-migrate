"""Local-only browser UI for read-only Codex history."""

VAULT_HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="data:,">
<title>Codex Migrate — Vault + Migration</title>
<style>
:root{color-scheme:dark;--bg:#080b10;--panel:#111722;--line:#344057;--text:#f7f8fa;--muted:#bdc7d8;--purple:#6042a6;--light:#d9cdff}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 20% 0,#172038 0,transparent 36%),var(--bg);color:var(--text);font:500 16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{width:min(960px,calc(100% - 32px));margin:36px auto 80px}a{color:var(--light)}header{display:flex;justify-content:space-between;gap:20px;align-items:flex-start;margin-bottom:28px}h1{font-size:clamp(34px,7vw,58px);letter-spacing:-.045em;line-height:1;margin:10px 0}.lede,.muted{color:var(--muted)}.lede{font-size:18px;max-width:680px;margin:0}.panel{background:color-mix(in srgb,var(--panel) 95%,transparent);border:1px solid var(--line);border-radius:18px;padding:22px;margin:18px 0}.summary{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.metric{border:1px solid var(--line);border-radius:13px;padding:14px}.metric span{display:block;color:var(--muted);font-size:14px}.metric strong{font-size:22px}form,.actions{display:flex;gap:10px;flex-wrap:wrap}input,select,textarea,button,a.button{font:inherit;border-radius:10px;border:1px solid #8996ad;padding:11px 14px}input,select,textarea{background:#080b10;color:var(--text);flex:1;min-width:220px}textarea{display:block;width:100%;resize:none}button,a.button{background:var(--purple);color:white;font-weight:750;cursor:pointer;text-decoration:none}button.secondary,a.secondary{background:transparent}button:disabled,select:disabled{opacity:.55;cursor:wait}.result{width:100%;text-align:left;background:#151d2a;margin:10px 0;padding:15px;line-height:1.45}.result small{display:block;color:var(--muted);margin-bottom:5px}.entry{border-top:1px solid var(--line);padding:20px 0}.entry:first-child{border-top:0}.entry h3{margin:0 0 4px;font-size:17px}.entry time{display:block;color:var(--muted);font-size:14px;margin-bottom:10px}.entry p{white-space:pre-wrap;overflow-wrap:anywhere;margin:0}#error,#backup-error,#schedule-error,#restore-error,#install-error{color:#ffc3c8}#status,#backup-status,#schedule-status,#restore-status,#install-status{color:var(--muted)}#recovery{border-left:4px solid var(--light);padding-left:16px;margin-top:18px}.subsection{border-top:1px solid var(--line);margin-top:22px;padding-top:18px}[hidden]{display:none!important}fieldset{margin:18px 0;padding:0;border:0}legend{margin-bottom:10px;font-weight:750}fieldset label{display:flex;gap:11px;padding:13px 14px;margin:8px 0;border:1px solid var(--line);border-radius:11px;cursor:pointer}fieldset input{flex:0 0 auto;min-width:0;width:19px;height:19px;margin:3px 0 0;accent-color:var(--purple)}fieldset label span,fieldset label small{display:block}fieldset label small{margin-top:3px;color:var(--muted);font-size:14px}.retention-note{font-size:14px;margin-top:10px}
.result strong{display:block;margin-bottom:4px}#browse-error,#thread-restore-error{color:#ffc3c8}#browse-status,#thread-restore-status{color:var(--muted)}
.app{min-height:100vh;display:grid;grid-template-columns:238px 1fr}.sidebar{position:sticky;top:0;height:100vh;padding:28px 18px 24px;border-right:1px solid var(--line);background:#0c1018;display:flex;flex-direction:column}.brand{display:flex;gap:12px;align-items:center;padding:0 8px 26px}.brand-mark{width:36px;height:36px;display:grid;place-items:center;border-radius:11px;background:linear-gradient(145deg,#9475ff,#5735d6);font-size:14px;font-weight:850;box-shadow:0 10px 30px #6f4cff44}.brand strong,.brand small{display:block}.brand small{color:var(--muted);font-size:12px}.nav{display:grid;gap:8px}.nav a{display:flex;align-items:center;gap:12px;padding:12px 14px;color:#aeb8ca;border-radius:11px;text-decoration:none;font-weight:700}.nav a:hover,.nav a.active{color:white;background:#1d2434}.nav-icon{width:18px;text-align:center;color:#a991ff}.protection{margin-top:auto;border-top:1px solid var(--line);padding:18px 8px 0;font-size:13px;color:var(--muted)}.protection strong{color:var(--text)}.dot{display:inline-block;width:9px;height:9px;margin-right:8px;border-radius:50%;background:#45dfa0;box-shadow:0 0 0 5px #45dfa014}.content{min-width:0}.topline{font-size:14px;color:var(--muted);font-weight:750}.view-head h1{font-size:clamp(38px,5vw,58px)}.view-head{align-items:center;margin-bottom:26px}.panel h2{margin-top:0}.storage-assessment{border:1px solid var(--line);border-radius:13px;padding:14px 16px;margin:14px 0;background:#0c121d}.storage-assessment strong,.storage-assessment span{display:block}.storage-assessment span{color:var(--muted);font-size:14px;margin-top:3px}.storage-assessment.cloud_sync{border-color:#25654d;background:#0d251c}.storage-assessment.cloud_sync strong{color:#5ee5aa}.storage-assessment.local{border-color:#7a5824;background:#2c210f}.storage-assessment.local strong{color:#ffd58a}.storage-assessment.external_or_network{border-color:#4c5a74}.view-backup .summary,.view-recovery .summary,.view-backup #restore-panel,.view-backup #search-panel,.view-backup #results-panel,.view-backup #thread,.view-conversations #backup-panel,.view-conversations #restore-panel,.view-recovery #backup-panel,.view-recovery #search-panel,.view-recovery #results-panel,.view-recovery #thread{display:none!important}.view-conversations main{width:min(1120px,calc(100% - 48px))}.view-conversations #search-panel{margin-bottom:12px}.view-conversations #results-panel{width:36%;float:left;margin-right:14px}.view-conversations #thread{overflow:hidden;min-height:420px}.view-conversations #status,.view-conversations #error{clear:both}.view-recovery main{width:min(980px,calc(100% - 48px))}
@media(max-width:820px){.app{display:block}.sidebar{position:static;width:auto;height:auto;padding:16px}.brand{padding-bottom:12px}.nav{display:flex;overflow-x:auto}.nav a{white-space:nowrap}.protection{display:none}.view-conversations #results-panel{float:none;width:auto;margin-right:0}.view-conversations #thread{min-height:0}}
@media(max-width:620px){header{display:block}.summary{grid-template-columns:1fr}.panel{padding:16px}main,.view-conversations main,.view-recovery main{width:min(100% - 24px,960px);margin-top:22px}.nav a{padding:10px}.nav-icon{display:none}}
@media print{body{background:white;color:black}header,.summary,#backup-panel,#restore-panel,#search-panel,#results-panel,.actions,#error,#status{display:none!important}main{width:auto;margin:0}.panel{border:0;padding:0;background:white}.entry{break-inside:avoid;border-color:#bbb}.entry time{color:#444}}
</style>
</head>
<body>
<div class="app">
<aside class="sidebar">
<div class="brand">
<div class="brand-mark">CM</div>
<div>
<strong>Codex Migrate</strong>
<small>Vault + Migration</small>
</div>
</div>
<nav class="nav" aria-label="Product">
<a data-route="overview" href="/?view=overview">
<span class="nav-icon">⌂</span>Overview</a>
<a data-route="backup" href="/vault?view=backup">
<span class="nav-icon">⟳</span>Backups</a>
<a data-route="conversations" href="/vault?view=conversations">
<span class="nav-icon">⌕</span>Conversations</a>
<a data-route="recovery" href="/vault?view=recovery">
<span class="nav-icon">↺</span>Recovery</a>
<a data-route="move" href="/?view=move">
<span class="nav-icon">⇢</span>Move Macs</a>
</nav>
<div class="protection">
<strong>Protection status</strong>
<br>Open Backups to see whether protection is current.</div>
</aside>
<div class="content">
<main>
<header class="view-head">
<div>
<div class="topline" id="view-kicker">Conversations</div>
<h1 id="view-title">Find any conversation.</h1>
<p class="lede" id="view-lede">Search active and archived Codex threads stored on this Mac.</p>
</div>
<a class="button secondary" href="#migration-help">Help</a>
</header>
<section class="summary" aria-label="Local history summary">
  <div class="metric">
<span>Active conversations</span>
<strong id="active">—</strong>
</div>
  <div class="metric">
<span>Archived conversations</span>
<strong id="archived">—</strong>
</div>
  <div class="metric">
<span>Transcript data</span>
<strong id="bytes">—</strong>
</div>
</section>
<section class="panel" id="backup-panel">
<h2>Backup settings</h2>
<p class="muted">Choose an empty local or cloud-sync folder, or your existing Vault. Conversation content is encrypted before it is written there.</p>
<div class="actions">
<input id="vault-folder" readonly placeholder="Choose a Vault folder">
<button id="choose-vault" class="secondary">Choose folder…</button>
</div>
<div id="storage-assessment" class="storage-assessment" hidden role="status" aria-live="polite">
<strong id="storage-heading"></strong>
<span id="storage-detail"></span>
</div>
<fieldset id="backup-frequency">
<legend>How should backups run?</legend>
<label>
<input id="backup-frequency-daily" type="radio" name="backup-frequency" value="daily" checked>
<span>
<strong>Back up automatically every day</strong>
<small>Recommended. Runs through macOS even when the app is closed. The Mac and Vault folder must be available.</small>
</span>
</label>
<label>
<input id="backup-frequency-manual" type="radio" name="backup-frequency" value="manual">
<span>
<strong>Back up only when I ask</strong>
<small>No background schedule. You can turn on daily backup later.</small>
</span>
</label>
</fieldset>
<div class="actions">
<button id="backup" disabled>Create backup + turn on daily backup</button>
</div>
<p class="muted retention-note">Existing snapshots are kept. Daily backup is not real-time sync.</p>
<p id="backup-status" role="status" aria-live="polite">
</p>
<p id="backup-error" role="alert">
</p>
<div id="recovery" hidden>
<h3>Save this recovery key</h3>
<p>Put it in your password manager. It is required if this Mac is lost, and it is not stored in the backup folder.</p>
<textarea id="recovery-key" readonly rows="3">
</textarea>
<div class="actions">
<button id="copy-recovery">Copy recovery key</button>
<button id="saved-recovery" class="secondary">I saved it</button>
</div>
</div>
<div class="subsection" id="schedule-controls" hidden>
<h3>Automatic backup</h3>
<p class="muted">The daily schedule starts only after a verified backup. You can turn it off without deleting existing snapshots.</p>
<div class="actions">
<button id="enable-schedule" disabled>Turn on daily backup</button>
<button id="disable-schedule" class="secondary" hidden>Turn off automatic backup</button>
</div>
<p id="schedule-status" role="status" aria-live="polite">
</p>
<p id="schedule-error" role="alert">
</p>
</div>
</section>
<section class="panel" id="restore-panel">
<h2>Recover a backup</h2>
<p class="muted">Choose a backup version. Open it privately to find and recover one missing conversation, or recover the complete copy into an empty folder.</p>
<div class="actions">
<input id="restore-vault" readonly placeholder="Choose an existing Vault">
<button id="choose-restore-vault" class="secondary">Choose Vault…</button>
</div>
<div class="actions">
<select id="restore-snapshot" aria-label="Backup version" disabled>
<option value="">Choose a Vault to see backups</option>
</select>
<button id="browse-backup" disabled>Open this backup</button>
</div>
<p id="browse-status" role="status" aria-live="polite">
</p>
<p id="browse-error" role="alert">
</p>
<details>
<summary>Recover the complete backup</summary>
<p class="muted">Recovering into an empty folder does not change live Codex data. Installing the complete backup replaces only conversation history and keeps a verified rollback copy.</p>
<div class="actions">
<input id="restore-output" readonly placeholder="Choose an empty recovery folder">
<button id="choose-restore-output" class="secondary">Choose empty folder…</button>
<button id="restore" disabled>Recover complete copy</button>
</div>
<p id="restore-status" role="status" aria-live="polite">
</p>
<p id="restore-error" role="alert">
</p>
<div class="subsection">
<h3>Replace conversation history</h3>
<p class="muted">Close Codex and its CLI sessions first. Authentication and installation identity stay unchanged.</p>
<div class="actions">
<button id="install" disabled>Install complete backup in Codex</button>
<button id="install-recover" class="secondary" hidden>Roll back interrupted installation</button>
</div>
<p id="install-status" role="status" aria-live="polite">
</p>
<p id="install-error" role="alert">
</p>
</div>
</details>
</section>
<section class="panel" id="search-panel">
<h2>Find a conversation</h2>
<form id="search">
<label class="muted" for="search-source">Search in</label>
<select id="search-source">
<option value="local">This Mac · Conversation text</option>
<option value="local_titles">This Mac · Current and old titles</option>
<option value="backup" disabled>Opened backup</option>
<option value="history">All saved titles</option>
</select>
<div id="history-location" class="actions" hidden>
<input id="history-vault" readonly placeholder="Choose your encrypted Vault" aria-label="Vault for saved title search">
<button id="choose-history-vault" type="button" class="secondary">Choose Vault…</button>
</div>
<label class="muted" for="query">Words or phrase</label>
<input id="query" required autocomplete="off">
<button type="submit">Search</button>
</form>
<p class="muted">Remember an old name? Search this Mac's titles first. Full-text search reads local conversations and may take longer for large histories. All saved titles searches dated encrypted snapshots; open a version to search its full text.</p>
</section>
<section class="panel" id="results-panel" hidden>
<h2>Results</h2>
<div id="results">
</div>
<button id="more-results" type="button" class="secondary" hidden>Show more conversations</button>
</section>
<section class="panel" id="thread" hidden>
<div class="actions">
<button id="restore-thread" hidden>Restore this conversation into Codex</button>
<button id="download">Download Markdown</button>
<button id="print" class="secondary">Print / Save PDF</button>
<button id="share" class="secondary">Share thread…</button>
</div>
<p class="muted" id="thread-restore-note" hidden>This adds one missing verified conversation. It never overwrites or merges an existing thread. Close Codex and its CLI sessions first.</p>
<p id="thread-restore-status" role="status" aria-live="polite">
</p>
<p id="thread-restore-error" role="alert">
</p>
<p class="muted" id="thread-meta">
</p>
<button id="read-from-start" type="button" class="secondary" hidden>Read from beginning</button>
<div id="thread-timeline" class="subsection" hidden>
<h3>Saved versions</h3>
<div id="versions"></div>
</div>
<div id="entries">
</div>
<button id="load-more" class="secondary" hidden>Load more messages</button>
</section>
<p id="status" role="status" aria-live="polite">Loading history…</p>
<p id="error" role="alert">
</p>
</main>
</div>
</div>
<script>
const $=id=>document.getElementById(id);
const tokenKey="codex-migrate-token:"+location.origin;
const incoming=new URLSearchParams(location.hash.slice(1)).get("token");
if(incoming)sessionStorage.setItem(tokenKey,incoming);
const token=incoming||sessionStorage.getItem(tokenKey)||"";
history.replaceState(null,"",location.pathname+location.search);
const requestedView=new URLSearchParams(location.search).get("view");
const view=["backup","conversations","recovery"].includes(requestedView)?requestedView:"conversations";
document.body.classList.add("view-"+view);
const viewCopy={backup:["Backups / Set up","Protect this Mac.","Choose where your encrypted Vault lives and how often Codex Migrate should update it."],conversations:["Conversations","Find any conversation.","Search active and archived Codex threads stored on this Mac."],recovery:["Recovery","Recover what matters.","Open a verified backup, restore one missing conversation, or recover complete history safely."]}[view];
$("view-kicker").textContent=viewCopy[0];$("view-title").textContent=viewCopy[1];$("view-lede").textContent=viewCopy[2];
for(const link of document.querySelectorAll("[data-route]")){link.classList.toggle("active",link.dataset.route===view);link.href=link.getAttribute("href")+"#token="+encodeURIComponent(token)}
const fmt=n=>{const units=["B","KB","MB","GB","TB"];let i=0;while(n>=1000&&i<units.length-1){n/=1000;i++}return `${n.toFixed(n>=100?0:n>=10?1:2)} ${units[i]}`};
async function api(path,data){const response=await fetch(path,{method:data===undefined?"GET":"POST",headers:{"X-Codex-Migrate-Token":token,"Content-Type":"application/json"},...(data===undefined?{}:{body:JSON.stringify(data)})});const type=response.headers.get("Content-Type")||"";const body=type.includes("application/json")?await response.json():await response.text();if(!response.ok)throw Error(body.error||"The local request failed");return body}
function fail(error){$("error").textContent=error.message;$("status").textContent=""}
const chosenVault=()=>$("history-vault").value||$("restore-vault").value;
$("search-source").onchange=()=>{$("history-location").hidden=$("search-source").value!=="history"};
$("choose-history-vault").onclick=async()=>{
  try{
    const result=await api("/api/vault/folder",{});
    if(result.path){$("history-vault").value=result.path;$("restore-vault").value=result.path;await refreshSnapshots()}
  }catch(error){fail(error)}
};
let selected=null;
let threadExcerpted=false;
function params(item){return new URLSearchParams({collection:item.collection,transcript:item.transcript,source:item.source||"local"})}
function appendEntries(entries){$("entries").append(...entries.map((entry,index)=>{
  const article=document.createElement("article");article.className="entry";
  const h=document.createElement("h3");h.textContent=entry.role||`Entry ${$("entries").children.length+index+1}`;article.append(h);
  if(entry.timestamp){const time=document.createElement("time");time.textContent=entry.timestamp;article.append(time)}
  if(entry.excerpted){const note=document.createElement("small");note.textContent="Excerpt from a long message. Download Markdown for its full text.";article.append(note)}
  const p=document.createElement("p");p.textContent=entry.text;article.append(p);return article;
}))}
async function openThread(item){
  $("error").textContent="";$("status").textContent="Opening conversation…";
  try{
    const fromMatch=Number.isSafeInteger(item.cursor)&&item.cursor>=0&&item.line>0;
    const query=params(item);
    if(fromMatch){query.set("cursor",String(item.cursor));query.set("match",item.match_query||"")}
    const thread=await api("/api/vault/thread?"+query);selected=item;
    const fromBackup=item.source==="backup";
    $("restore-thread").hidden=!fromBackup;
    $("thread-restore-note").hidden=!fromBackup;
    $("thread-restore-status").textContent="";$("thread-restore-error").textContent="";
    threadExcerpted=thread.entries.some(entry=>entry.excerpted);
    $("thread-meta").textContent=`${fromBackup?"Opened backup":"This Mac"} · ${thread.collection} · ${fromMatch?"Starting at the search match · ":""}${thread.entries.length} readable entries${threadExcerpted?". A long message is excerpted here; Download Markdown for full text.":thread.next_cursor!==null&&thread.next_cursor!==undefined?" so far. Download Markdown includes the full conversation.":""}`;
    $("read-from-start").hidden=!fromMatch||item.cursor===0;
    $("entries").replaceChildren();appendEntries(thread.entries);
    $("load-more").dataset.cursor=thread.next_cursor===null||thread.next_cursor===undefined?"":String(thread.next_cursor);
    $("load-more").hidden=!$("load-more").dataset.cursor;
    $("print").hidden=threadExcerpted||Boolean($("load-more").dataset.cursor);
    $("share").hidden=threadExcerpted||Boolean($("load-more").dataset.cursor);
    $("thread-timeline").hidden=true;$("versions").replaceChildren();
    if(fromBackup&&item.key&&chosenVault()){
      const data=await api("/api/vault/thread-history?"+new URLSearchParams({vault:chosenVault(),key:item.key}));
      $("versions").replaceChildren(...data.versions.map(version=>{
        const button=document.createElement("button");button.type="button";button.className="result";
        const when=new Date(version.created_at);
        const label=Number.isNaN(when.getTime())?version.created_at:when.toLocaleString();
        button.textContent=`${label} · ${version.titles.at(-1)||"Untitled"} · ${fmt(version.size)}${version.at_risk?" · Needs review":""}`;
        button.onclick=()=>openSavedResult({matching_snapshot:version.snapshot_id,
          matching_collection:version.collection,matching_transcript:version.transcript,key:item.key});
        return button;
      }));
      $("thread-timeline").hidden=data.versions.length<2;
    }
    $("thread").hidden=false;$("status").textContent="";
    const matched=fromMatch&&item.match_query?[...$("entries").querySelectorAll("p")].find(
      p=>p.textContent.toLocaleLowerCase().includes(item.match_query.toLocaleLowerCase())):null;
    (matched||$("thread")).scrollIntoView({behavior:"smooth"});
  }catch(error){
    if(item.source==="backup"||item.source==="local"){
      selected=item;$("entries").replaceChildren();$("load-more").hidden=true;
      $("print").hidden=true;$("share").hidden=true;$("read-from-start").hidden=true;$("restore-thread").hidden=item.source!=="backup";
      $("thread-meta").textContent="This conversation cannot be previewed here. Try its Markdown export or another saved version.";
      $("thread").hidden=false;
    }
    fail(error)
  }
}
$("read-from-start").onclick=()=>{if(selected)openThread({...selected,cursor:0,line:0,match_query:""})};
$("load-more").onclick=async()=>{
  if(!selected||!$("load-more").dataset.cursor)return;
  $("load-more").disabled=true;
  try{
    const query=params(selected);query.set("cursor",$("load-more").dataset.cursor);
    const page=await api("/api/vault/thread?"+query);appendEntries(page.entries);
    threadExcerpted=threadExcerpted||page.entries.some(entry=>entry.excerpted);
    $("load-more").dataset.cursor=page.next_cursor===null?"":String(page.next_cursor);
    $("load-more").hidden=!$("load-more").dataset.cursor;
    const fromMatch=Number.isSafeInteger(selected.cursor)&&selected.cursor>=0&&selected.line>0;
    $("thread-meta").textContent=`${selected.source==="backup"?"Opened backup":"This Mac"} · ${page.collection} · ${fromMatch?"Starting at the search match · ":""}${$("entries").children.length} readable entries${threadExcerpted?". A long message is excerpted here; Download Markdown for full text.":page.next_cursor!==null?" so far. Download Markdown includes the full conversation.":""}`;
    $("print").hidden=threadExcerpted||Boolean($("load-more").dataset.cursor);
    $("share").hidden=threadExcerpted||Boolean($("load-more").dataset.cursor);
  }catch(error){fail(error)}finally{$("load-more").disabled=false}
};
async function openSavedResult(item){
  const vault=chosenVault();
  if(!vault){$("status").textContent="Choose your Vault in Recovery first.";return}
  $("restore-vault").value=vault;
  $("status").textContent="Verifying and opening saved version…";
  try{
    $("restore-snapshot").dataset.requested=item.matching_snapshot;
    await refreshSnapshots();
    if(![...$("restore-snapshot").options].some(option=>option.value===item.matching_snapshot))
      throw Error("This version is outside the visible snapshot list. Open it from Recovery.");
    $("restore-snapshot").value=item.matching_snapshot;
    invalidateOpenedChoice();
    await api("/api/vault/browse",{vault,snapshot:item.matching_snapshot,apply:true});
    for(let attempt=0;attempt<300;attempt++){
      await new Promise(resolve=>setTimeout(resolve,1000));
      const state=await api("/api/vault/browse-status");
      if(state.status==="failed")throw Error(state.error||"The saved version could not be opened.");
      if(state.status==="ready"&&state.snapshot_id===item.matching_snapshot){
        browseView(state);
        await openThread({collection:item.matching_collection,transcript:item.matching_transcript,
          source:"backup",key:item.key});
        return;
      }
    }
    throw Error("The saved version is still opening. Check Recovery before retrying.");
  }catch(error){fail(error)}
}
let searchPage=null;
let searchRequest=0;
async function runSearch(append=false){
  const source=$("search-source").value,query=$("query").value.trim();
  if(append&&(!searchPage||searchPage.source!==source||searchPage.query!==query))append=false;
  if(!append){searchRequest++;$("error").textContent="";$("thread").hidden=true;$("more-results").hidden=true;searchPage={source,query,offset:0}}
  const request=searchRequest;
  const offset=append?searchPage.offset:0;
  $("more-results").disabled=true;
  $("status").textContent=source==="history"?"Searching saved titles…":
    source==="backup"?"Searching the opened backup…":
    source==="local_titles"?"Searching current and old titles…":"Searching this Mac…";
  try{
    let data;
    if(source==="history"){
      const vault=chosenVault();
      if(!vault)throw Error("Choose your Vault before searching saved titles.");
      data=await api("/api/vault/history-search?"+new URLSearchParams({vault,q:query}));
    }else data=await api("/api/vault/search?"+new URLSearchParams({q:query,limit:"50",offset:String(offset),source}));
    if(request!==searchRequest)return;
    const buttons=data.results.map(item=>{
      const button=document.createElement("button");button.type="button";button.className="result";
      const small=document.createElement("small"),text=document.createElement("span"),title=document.createElement("strong");
      if(source==="history"){
        small.textContent=`${item.version_count} saved ${item.version_count===1?"version":"versions"} · ${item.identity_state}${item.at_risk?" · Needs review":""}`;
        text.textContent=item.matching_title;
        button.onclick=()=>openSavedResult(item);
      }else{
        item.source=source==="local_titles"?"local":source;
        item.match_query=query;
        small.textContent=`${item.collection}${item.timestamp?" · "+item.timestamp:""}`;
        if(item.title)title.textContent=item.title;
        text.textContent=item.snippet;button.onclick=()=>openThread(item);
      }
      button.append(small);if(title.textContent)button.append(title);button.append(text);return button;
    });
    if(append)$("results").append(...buttons);else $("results").replaceChildren(...buttons);
    searchPage.offset=offset+data.results.length;
    $("more-results").hidden=source==="history"||!data.has_more;
    $("results-panel").hidden=false;
    const count=$("results").children.length;
    $("status").textContent=count?(data.has_more?
      `${count} matching conversations shown. Show more or add more words to narrow the results.`:
      `${count} matching conversation${count===1?"":"s"}. Select one to open it.`):
      source==="history"?"No matching saved title found. Choose one dated backup to search its full text.":
      source==="local_titles"?"No matching local title found. Try searching conversation text.":
      "No matching conversation text found.";
  }catch(error){if(request===searchRequest)fail(error)}finally{if(request===searchRequest)$("more-results").disabled=false}
}
$("search").onsubmit=event=>{event.preventDefault();void runSearch()};
$("more-results").onclick=()=>void runSearch(true);
async function markdownFile(){if(!selected)throw Error("Open a conversation first");const text=await api("/api/vault/export?"+params(selected));return new File([text],"codex-conversation.md",{type:"text/markdown"})}
$("download").onclick=async()=>{try{
  if(!selected)throw Error("Open a conversation first");
  const link=document.createElement("a");link.download="codex-conversation.md";
  const grant=await api("/api/vault/export-ticket",{collection:selected.collection,transcript:selected.transcript,source:selected.source||"local"});
  link.href=grant.url;link.click();$("status").textContent="Downloading the full conversation…";
}catch(error){fail(error)}};
$("print").onclick=()=>window.print();
$("share").onclick=async()=>{try{const file=await markdownFile();if(navigator.share&&(!navigator.canShare||navigator.canShare({files:[file]}))){await navigator.share({title:"Codex conversation",files:[file]});$("status").textContent="Share sheet opened."}else{$("status").textContent="This browser cannot open the share sheet. Use Download Markdown, then share or email the file."}}catch(error){if(error.name!=="AbortError")fail(error)}};
let backupTimer=null;
let installRunning=false;
let verifiedBackup=false;
let pendingAutomaticBackup=false;
function storageView(storage){const panel=$("storage-assessment");if(!storage){panel.hidden=true;return}panel.hidden=false;panel.className="storage-assessment "+storage.kind;$("storage-heading").textContent=storage.heading;$("storage-detail").textContent=storage.detail}
async function refreshStorage(path){if(!path){storageView(null);return}try{storageView(await api("/api/vault/storage?path="+encodeURIComponent(path)))}catch(error){storageView({kind:"external_or_network",heading:"Storage protection unverified",detail:"Codex Migrate could not classify this location. Confirm how it is backed up before relying on it after loss of the Mac."})}}
function backupFrequencyView(){const daily=$("backup-frequency-daily").checked;$("backup").textContent=daily?"Create backup + turn on daily backup":"Create encrypted backup"}
function backupView(data){const running=data.status==="running";if(data.storage)storageView(data.storage);if(data.destination&&!$("vault-folder").value){$("vault-folder").value=data.destination;if(!data.storage)refreshStorage(data.destination)}if(data.destination&&!$("restore-vault").value){$("restore-vault").value=data.destination;refreshSnapshots()}verifiedBackup=["completed","needs_attention"].includes(data.status)&&!data.recovery_key;$("choose-vault").disabled=running||installRunning;$("backup-frequency-daily").disabled=running||installRunning||scheduleEnabled;$("backup-frequency-manual").disabled=running||installRunning||scheduleEnabled;$("backup").disabled=running||installRunning||!$("vault-folder").value||Boolean(data.recovery_key);$("backup-error").textContent=data.status==="failed"?(data.error||"Encrypted backup stopped safely."):"";if(running){const files=`${data.completed_files||0} of ${data.total_files||0} files`;const bytes=data.total_bytes?` · ${Math.round(100*(data.completed_bytes||0)/data.total_bytes)}% of ${fmt(data.total_bytes)}`:"";$("backup-status").textContent="Encrypting and verifying… "+files+bytes}else if(data.status==="completed"){$("backup-status").textContent=`Verified snapshot complete · ${data.transcript_files.toLocaleString()} files · ${fmt(data.transcript_bytes)}`}else if(data.status==="needs_attention"){$("backup-status").textContent=`Verified snapshot saved, but ${data.at_risk_threads} conversation${data.at_risk_threads===1?"":"s"} may have lost content. Open an earlier saved version for review.`}else if(data.status==="failed"){$("backup-status").textContent=""}else{$("backup-status").textContent="No backup is running."}if(data.recovery_key){$("recovery-key").value=data.recovery_key;$("recovery").hidden=false}else{$("recovery-key").value="";$("recovery").hidden=true}if(running&&!backupTimer)backupTimer=setInterval(refreshBackup,1500);if(!running&&backupTimer){clearInterval(backupTimer);backupTimer=null}refreshScheduleButton();refreshRestoreButton();if(verifiedBackup&&data.status!=="needs_attention"&&pendingAutomaticBackup&&!scheduleEnabled)void enableRequestedSchedule()}
async function refreshBackup(){try{backupView(await api("/api/vault/backup-status"))}catch(error){$("backup-error").textContent=error.message}}
$("choose-vault").onclick=async()=>{try{$("backup-error").textContent="";const result=await api("/api/vault/folder",{});if(result.path){$("vault-folder").value=result.path;$("restore-vault").value=result.path;storageView(result.storage);verifiedBackup=false;$("backup").disabled=false;$("backup-status").textContent="Folder selected. Review its protection, then create the backup when ready.";refreshScheduleButton();await refreshSnapshots()}}catch(error){$("backup-error").textContent=error.message}};
$("backup-frequency-daily").onchange=backupFrequencyView;
$("backup-frequency-manual").onchange=backupFrequencyView;
$("backup").onclick=async()=>{try{$("backup-error").textContent="";pendingAutomaticBackup=$("backup-frequency-daily").checked;backupView(await api("/api/vault/backup",{destination:$("vault-folder").value,apply:true}))}catch(error){pendingAutomaticBackup=false;$("backup-error").textContent=error.message}};
$("copy-recovery").onclick=async()=>{try{await navigator.clipboard.writeText($("recovery-key").value);$("backup-status").textContent="Recovery key copied. Save it in your password manager."}catch(error){$("backup-error").textContent="Copy failed. Select the recovery key and copy it manually."}};
$("saved-recovery").onclick=async()=>{try{const result=await api("/api/vault/recovery-saved",{});backupView(result);$("backup-status").textContent=result.status==="completed"?"Recovery key acknowledged. The verified backup is ready.":"Recovery key acknowledged. Retry the encrypted backup."}catch(error){$("backup-error").textContent=error.message}};
let scheduleEnabled=false;
function refreshScheduleButton(){$("schedule-controls").hidden=!verifiedBackup&&!scheduleEnabled;$("enable-schedule").hidden=scheduleEnabled;$("disable-schedule").hidden=!scheduleEnabled;$("enable-schedule").disabled=installRunning||!verifiedBackup||!$("vault-folder").value;$("disable-schedule").disabled=installRunning}
function scheduleView(data){scheduleEnabled=Boolean(data.enabled);if(data.storage)storageView(data.storage);if(scheduleEnabled){$("backup-frequency-daily").checked=true;$("backup-frequency-manual").checked=false}if(data.vault&&!$("vault-folder").value){$("vault-folder").value=data.vault;if(!data.storage)refreshStorage(data.vault)}if(data.vault&&!$("restore-vault").value){$("restore-vault").value=data.vault;refreshSnapshots()}$("schedule-error").textContent=data.error||"";if(!data.enabled){$("schedule-status").textContent="Automatic backup is off."}else if(data.healthy){let detail="Daily encrypted backup is on.";if(data.last_run?.status==="completed")detail+=" Last backup completed "+(data.last_run.completed_at||"")+".";else if(data.last_run?.status==="failed")detail+=" The last automatic backup needs attention.";$("schedule-status").textContent=detail}else{$("schedule-status").textContent="Automatic backup needs attention."}backupFrequencyView();refreshScheduleButton();refreshRestoreButton()}
async function refreshSchedule(){try{scheduleView(await api("/api/vault/schedule"))}catch(error){$("schedule-error").textContent=error.message}}
async function enableDailySchedule(){try{$("schedule-error").textContent="";$("enable-schedule").disabled=true;scheduleView(await api("/api/vault/schedule",{destination:$("vault-folder").value,interval_hours:24,apply:true}))}catch(error){$("schedule-error").textContent=error.message+" The verified backup is safe; turn on daily backup again when ready.";refreshScheduleButton()}}
async function enableRequestedSchedule(){pendingAutomaticBackup=false;$("schedule-status").textContent="Verified backup complete. Turning on daily backup…";await enableDailySchedule()}
$("enable-schedule").onclick=enableDailySchedule;
$("disable-schedule").onclick=async()=>{try{$("schedule-error").textContent="";$("backup-frequency-manual").checked=true;$("backup-frequency-daily").checked=false;scheduleView(await api("/api/vault/schedule-remove",{apply:true}))}catch(error){$("schedule-error").textContent=error.message}};
let restoreTimer=null;
let browseRunning=false;
let selectedRecoveryRunning=false;
function refreshRestoreButton(){const chosen=$("restore-vault").value&&$("restore-snapshot").value;$("browse-backup").disabled=installRunning||browseRunning||selectedRecoveryRunning||!chosen;$("restore").disabled=installRunning||browseRunning||selectedRecoveryRunning||!chosen||!$("restore-output").value;$("install").disabled=installRunning||browseRunning||selectedRecoveryRunning||!chosen}
async function refreshSnapshots(){const vault=$("restore-vault").value;const select=$("restore-snapshot");const selected=select.dataset.requested||select.value;select.dataset.ready="";select.disabled=true;select.replaceChildren(new Option(vault?"Loading backup history…":"Choose a Vault to see backups",""));refreshRestoreButton();if(!vault)return;try{const data=await api("/api/vault/snapshots?vault="+encodeURIComponent(vault));if(!data.snapshots.length){select.replaceChildren(new Option("No published backups found",""));return}select.replaceChildren(...data.snapshots.map(item=>{const when=new Date(item.created_at);const label=(Number.isNaN(when.getTime())?item.created_at:when.toLocaleString())+(item.latest?" · Latest":"");return new Option(label,item.snapshot_id)}));if(selected&&[...select.options].some(option=>option.value===selected))select.value=selected;select.dataset.ready="true";select.disabled=false;$("restore-error").textContent=""}catch(error){select.replaceChildren(new Option("Backup history unavailable",""));$("restore-error").textContent=error.message}finally{refreshRestoreButton()}}
function restoreView(data){const running=data.status==="running";if(data.snapshot||data.snapshot_id)$("restore-snapshot").dataset.requested=data.snapshot||data.snapshot_id;if(data.vault&&!$("restore-vault").value){$("restore-vault").value=data.vault;refreshSnapshots()}if(data.output&&!$("restore-output").value)$("restore-output").value=data.output;$("choose-restore-vault").disabled=running||installRunning;$("choose-restore-output").disabled=running||installRunning;$("restore-snapshot").disabled=running||installRunning||$("restore-snapshot").dataset.ready!=="true";$("restore").disabled=running||installRunning||!$("restore-vault").value||!$("restore-snapshot").value||!$("restore-output").value;$("restore-error").textContent=data.status==="failed"?(data.error||"Recovery stopped safely."):"";if(running){$("restore-status").textContent="Verifying and recovering the selected backup…"}else if(data.status==="completed"){$("restore-status").textContent=`Recovered copy ready · ${data.transcript_files.toLocaleString()} files · ${fmt(data.transcript_bytes)}`}else if(data.status==="failed"){$("restore-status").textContent=""}else{$("restore-status").textContent="No recovery is running."}if(running&&!restoreTimer)restoreTimer=setInterval(refreshRestore,1500);if(!running&&restoreTimer){clearInterval(restoreTimer);restoreTimer=null}}
async function refreshRestore(){try{restoreView(await api("/api/vault/restore-status"))}catch(error){$("restore-error").textContent=error.message}}
$("choose-restore-vault").onclick=async()=>{try{$("restore-error").textContent="";const result=await api("/api/vault/folder",{});if(result.path){$("restore-vault").value=result.path;await refreshSnapshots()}}catch(error){$("restore-error").textContent=error.message}};
$("choose-restore-output").onclick=async()=>{try{$("restore-error").textContent="";const result=await api("/api/vault/restore-folder",{});if(result.path){$("restore-output").value=result.path;refreshRestoreButton()}}catch(error){$("restore-error").textContent=error.message}};
function invalidateOpenedChoice(){const option=$("search-source").querySelector('option[value="backup"]');option.disabled=true;if($("search-source").value==="backup")$("search-source").value="local";$("browse-status").textContent="Open the selected backup to search it.";searchRequest++;searchPage=null;$("more-results").hidden=true;$("results-panel").hidden=true;$("thread").hidden=true;refreshRestoreButton()}
$("restore-snapshot").onchange=invalidateOpenedChoice;
$("restore").onclick=async()=>{try{$("restore-error").textContent="";restoreView(await api("/api/vault/restore",{vault:$("restore-vault").value,output:$("restore-output").value,snapshot:$("restore-snapshot").value,apply:true}))}catch(error){$("restore-error").textContent=error.message}};
let browseTimer=null;
function browseView(data){browseRunning=data.status==="running";$("browse-error").textContent=data.status==="failed"?(data.error||"The backup could not be opened safely."):"";if(browseRunning){$("browse-status").textContent="Verifying, decrypting, and opening this backup privately…"}else if(data.status==="ready"){const option=$("search-source").querySelector('option[value="backup"]');option.disabled=false;$("search-source").value="backup";$("browse-status").textContent=`Backup ready to search · ${data.transcript_files.toLocaleString()} conversations · ${fmt(data.transcript_bytes)}`;$("results-panel").hidden=true;$("thread").hidden=true;$("status").textContent="Enter words from the conversation you want to recover."}else if(data.status==="failed"){const option=$("search-source").querySelector('option[value="backup"]');option.disabled=true;if($("search-source").value==="backup")$("search-source").value="local";$("browse-status").textContent=""}else{$("browse-status").textContent="No backup is open."}if(browseRunning&&!browseTimer)browseTimer=setInterval(refreshBrowse,1000);if(!browseRunning&&browseTimer){clearInterval(browseTimer);browseTimer=null}refreshRestoreButton()}
async function refreshBrowse(){try{browseView(await api("/api/vault/browse-status"))}catch(error){$("browse-error").textContent=error.message}}
$("browse-backup").onclick=async()=>{try{$("browse-error").textContent="";invalidateOpenedChoice();browseView(await api("/api/vault/browse",{vault:$("restore-vault").value,snapshot:$("restore-snapshot").value,apply:true}))}catch(error){$("browse-error").textContent=error.message}};
let installTimer=null;
function installView(data){installRunning=data.status==="running"||data.status==="rolling_back";const interrupted=data.status==="interrupted";$("install-recover").hidden=!interrupted;$("install-error").textContent=(data.status==="failed"||interrupted)?(data.error||"Installation needs attention."):"";if(data.status==="running"){$("install-status").textContent="Verifying the backup, creating a rollback copy, and installing conversation history…"}else if(data.status==="rolling_back"){$("install-status").textContent="Restoring and verifying the previous conversation history…"}else if(data.status==="completed"){$("install-status").textContent=`Installed and verified · ${data.transcript_files.toLocaleString()} files · Rollback backup: ${data.backup}`}else if(data.status==="rolled_back"){$("install-status").textContent="Previous conversation history restored and verified. You can retry when Codex is closed."}else if(interrupted){$("install-status").textContent="An interrupted installation must be rolled back before another install."}else if(data.status==="failed"){$("install-status").textContent=""}else{$("install-status").textContent="No installation is running."}refreshRestoreButton();$("choose-restore-vault").disabled=installRunning;$("choose-restore-output").disabled=installRunning;$("restore-snapshot").disabled=installRunning||$("restore-snapshot").dataset.ready!=="true";if(installRunning&&!installTimer)installTimer=setInterval(refreshInstall,1500);if(!installRunning&&installTimer){clearInterval(installTimer);installTimer=null}refreshBackup()}
async function refreshInstall(){try{installView(await api("/api/vault/install-status"))}catch(error){$("install-error").textContent=error.message}}
$("install").onclick=async()=>{if(!confirm("Install this backup version into Codex conversation history? Keep Codex closed. A rollback backup will be created first."))return;try{$("install-error").textContent="";installView(await api("/api/vault/install",{vault:$("restore-vault").value,snapshot:$("restore-snapshot").value,apply:true}))}catch(error){$("install-error").textContent=error.message}};
$("install-recover").onclick=async()=>{if(!confirm("Roll back the interrupted installation and restore the previous conversation history? Keep Codex closed."))return;try{$("install-error").textContent="";installView(await api("/api/vault/install-recover",{apply:true}))}catch(error){$("install-error").textContent=error.message}};
let selectedRecoveryTimer=null;
function selectedRecoveryView(data){selectedRecoveryRunning=data.status==="running";const attention=data.status==="needs_attention";$("restore-thread").disabled=selectedRecoveryRunning||installRunning||attention;$("thread-restore-error").textContent=(data.status==="failed"||attention)?(data.error||"Selected recovery stopped safely."):"";if(data.status==="running"){$("thread-restore-status").textContent="Verifying the backup again and recovering this conversation…"}else if(data.status==="installed"){$("thread-restore-status").textContent="Conversation restored and verified. Reopen Codex to use it."}else if(data.status==="already_present"){$("thread-restore-status").textContent="This exact conversation is already present. Nothing was changed."}else if(data.status==="failed"||attention){$("thread-restore-status").textContent=""}if(selectedRecoveryRunning&&!selectedRecoveryTimer)selectedRecoveryTimer=setInterval(refreshSelectedRecovery,1000);if(!selectedRecoveryRunning&&selectedRecoveryTimer){clearInterval(selectedRecoveryTimer);selectedRecoveryTimer=null}refreshRestoreButton()}
async function refreshSelectedRecovery(){try{selectedRecoveryView(await api("/api/vault/thread-install-status"))}catch(error){$("thread-restore-error").textContent=error.message}}
$("restore-thread").onclick=async()=>{if(!selected||selected.source!=="backup")return;if(!confirm("Restore only this verified conversation into Codex? Close Codex and its CLI sessions first. Existing conversations will not be overwritten or merged."))return;try{$("thread-restore-error").textContent="";selectedRecoveryView(await api("/api/vault/install-thread",{collection:selected.collection,transcript:selected.transcript,apply:true}))}catch(error){$("thread-restore-error").textContent=error.message}};
api("/api/vault/summary").then(data=>{$("active").textContent=data.active_transcripts.toLocaleString();$("archived").textContent=data.archived_transcripts.toLocaleString();$("bytes").textContent=fmt(data.transcript_bytes);$("status").textContent="Ready."}).catch(fail);
refreshBackup();
refreshSchedule();
refreshRestore();
refreshInstall();
refreshBrowse();
refreshSelectedRecovery();
backupFrequencyView();
</script>
</body>
</html>'''
