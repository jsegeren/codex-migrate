"""Local-only browser UI for read-only Codex history."""

VAULT_HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="data:,"><title>Codex Vault — Local history</title>
<style>
:root{color-scheme:dark;--bg:#080b10;--panel:#111722;--line:#344057;--text:#f7f8fa;--muted:#bdc7d8;--purple:#6042a6;--light:#d9cdff}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 20% 0,#172038 0,transparent 36%),var(--bg);color:var(--text);font:500 16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{width:min(960px,calc(100% - 32px));margin:36px auto 80px}a{color:var(--light)}header{display:flex;justify-content:space-between;gap:20px;align-items:flex-start;margin-bottom:28px}h1{font-size:clamp(34px,7vw,58px);letter-spacing:-.045em;line-height:1;margin:10px 0}.lede,.muted{color:var(--muted)}.lede{font-size:18px;max-width:680px;margin:0}.panel{background:color-mix(in srgb,var(--panel) 95%,transparent);border:1px solid var(--line);border-radius:18px;padding:22px;margin:18px 0}.summary{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.metric{border:1px solid var(--line);border-radius:13px;padding:14px}.metric span{display:block;color:var(--muted);font-size:14px}.metric strong{font-size:22px}form,.actions{display:flex;gap:10px;flex-wrap:wrap}input,button,a.button{font:inherit;border-radius:10px;border:1px solid #8996ad;padding:11px 14px}input{background:#080b10;color:var(--text);flex:1;min-width:220px}button,a.button{background:var(--purple);color:white;font-weight:750;cursor:pointer;text-decoration:none}button.secondary,a.secondary{background:transparent}.result{width:100%;text-align:left;background:#151d2a;margin:10px 0;padding:15px;line-height:1.45}.result small{display:block;color:var(--muted);margin-bottom:5px}.entry{border-top:1px solid var(--line);padding:20px 0}.entry:first-child{border-top:0}.entry h3{margin:0 0 4px;font-size:17px}.entry time{display:block;color:var(--muted);font-size:14px;margin-bottom:10px}.entry p{white-space:pre-wrap;overflow-wrap:anywhere;margin:0}#error{color:#ffc3c8}#status{color:var(--muted)}[hidden]{display:none!important}
@media(max-width:620px){header{display:block}.summary{grid-template-columns:1fr}.panel{padding:16px}main{margin-top:22px}}
@media print{body{background:white;color:black}header,.summary,#search-panel,#results-panel,.actions,#error,#status{display:none!important}main{width:auto;margin:0}.panel{border:0;padding:0;background:white}.entry{break-inside:avoid;border-color:#bbb}.entry time{color:#444}}
</style></head><body><main>
<header><div><a id="back" href="/">← Migration</a><h1>Codex Vault</h1><p class="lede">Find and export the Codex conversations stored on this Mac. Nothing is uploaded or changed.</p></div></header>
<section class="summary" aria-label="Local history summary">
  <div class="metric"><span>Active conversations</span><strong id="active">—</strong></div>
  <div class="metric"><span>Archived conversations</span><strong id="archived">—</strong></div>
  <div class="metric"><span>Transcript data</span><strong id="bytes">—</strong></div>
</section>
<section class="panel" id="search-panel"><h2>Search local history</h2><form id="search"><label class="muted" for="query">Words or phrase</label><input id="query" required autocomplete="off"><button type="submit">Search</button></form><p class="muted">The first version searches transcript files directly, so a very large history can take time. A private local index will make this faster later.</p></section>
<section class="panel" id="results-panel" hidden><h2>Results</h2><div id="results"></div></section>
<section class="panel" id="thread" hidden><div class="actions"><button id="download">Download Markdown</button><button id="print" class="secondary">Print / Save PDF</button><button id="share" class="secondary">Share thread…</button></div><p class="muted" id="thread-meta"></p><div id="entries"></div></section>
<p id="status" role="status" aria-live="polite">Loading history…</p><p id="error" role="alert"></p>
</main><script>
const $=id=>document.getElementById(id);
const tokenKey="codex-migrate-token:"+location.origin;
const incoming=new URLSearchParams(location.hash.slice(1)).get("token");
if(incoming)sessionStorage.setItem(tokenKey,incoming);
const token=incoming||sessionStorage.getItem(tokenKey)||"";
history.replaceState(null,"",location.pathname);
$("back").href="/#token="+encodeURIComponent(token);
const fmt=n=>{const units=["B","KB","MB","GB","TB"];let i=0;while(n>=1000&&i<units.length-1){n/=1000;i++}return `${n.toFixed(n>=100?0:n>=10?1:2)} ${units[i]}`};
async function api(path){const response=await fetch(path,{headers:{"X-Codex-Migrate-Token":token}});const type=response.headers.get("Content-Type")||"";const body=type.includes("application/json")?await response.json():await response.text();if(!response.ok)throw Error(body.error||"The local request failed");return body}
function fail(error){$("error").textContent=error.message;$("status").textContent=""}
let selected=null;
function params(item){return new URLSearchParams({collection:item.collection,transcript:item.transcript})}
async function openThread(item){$("error").textContent="";$("status").textContent="Opening conversation…";try{const thread=await api("/api/vault/thread?"+params(item));selected=item;$("thread-meta").textContent=`${thread.collection} · ${thread.entries.length} readable entries`;$("entries").replaceChildren(...thread.entries.map((entry,index)=>{const article=document.createElement("article");article.className="entry";const h=document.createElement("h3");h.textContent=entry.role||`Entry ${index+1}`;article.append(h);if(entry.timestamp){const time=document.createElement("time");time.textContent=entry.timestamp;article.append(time)}const p=document.createElement("p");p.textContent=entry.text;article.append(p);return article}));$("thread").hidden=false;$("status").textContent="";$("thread").scrollIntoView({behavior:"smooth"})}catch(error){fail(error)}}
$("search").onsubmit=async event=>{event.preventDefault();$("error").textContent="";$("status").textContent="Searching local transcripts…";$("thread").hidden=true;try{const query=$("query").value.trim();const data=await api("/api/vault/search?"+new URLSearchParams({q:query,limit:"50"}));$("results").replaceChildren(...data.results.map(item=>{const button=document.createElement("button");button.type="button";button.className="result";const small=document.createElement("small");small.textContent=`${item.collection}${item.timestamp?" · "+item.timestamp:""}`;const text=document.createElement("span");text.textContent=item.snippet;button.append(small,text);button.onclick=()=>openThread(item);return button}));$("results-panel").hidden=false;$("status").textContent=data.results.length?`${data.results.length} result${data.results.length===1?"":"s"}. Select one to open it.`:"No matching conversation text found."}catch(error){fail(error)}};
async function markdownFile(){if(!selected)throw Error("Open a conversation first");const text=await api("/api/vault/export?"+params(selected));return new File([text],"codex-conversation.md",{type:"text/markdown"})}
$("download").onclick=async()=>{try{const file=await markdownFile(),url=URL.createObjectURL(file),link=document.createElement("a");link.href=url;link.download=file.name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}catch(error){fail(error)}};
$("print").onclick=()=>window.print();
$("share").onclick=async()=>{try{const file=await markdownFile();if(navigator.share&&(!navigator.canShare||navigator.canShare({files:[file]}))){await navigator.share({title:"Codex conversation",files:[file]});$("status").textContent="Share sheet opened."}else{$("status").textContent="This browser cannot open the share sheet. Use Download Markdown, then share or email the file."}}catch(error){if(error.name!=="AbortError")fail(error)}};
api("/api/vault/summary").then(data=>{$("active").textContent=data.active_transcripts.toLocaleString();$("archived").textContent=data.archived_transcripts.toLocaleString();$("bytes").textContent=fmt(data.transcript_bytes);$("status").textContent="Ready."}).catch(fail);
</script></body></html>'''
