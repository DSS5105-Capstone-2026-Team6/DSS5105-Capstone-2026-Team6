/* Dispatch Desk static UI — all state comes from /api/state after each action. */
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const api = (p, opt) => fetch(p, opt).then(r => r.json());
const post = (p, body) => api(p, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)});
const del = p => fetch(p, {method:"DELETE"}).then(r => r.json());

const BADGE = {allocate:["ALLOCATE","#d3f9d8"],refuse:["REFUSE","#ffe3e3"],
  impossible:["IMPOSSIBLE","#ffe8cc"],ask:["ASK","#d0ebff"],
  answer:["ANSWER","#e9ecef"],no_data:["NO DATA","#e9ecef"]};
const NEEDS_HUMAN = new Set(["ask","refuse","impossible","no_data"]);
let STATE = null, CASE = "allocate", TAB = "desk";

function status(t){ const el=$("status"); if(el) el.textContent = t; }
async function refresh(){ STATE = await api("/api/state"); render(); }
function caseOf(d){ return d.behaviour === "answer" ? "no_data" : d.behaviour; }

/* ---------------- render root ---------------- */
function render(){
  renderRail(); renderKpis(); renderWorklist(); renderRecords(); renderProvider(); renderChatLog();
  if (TAB === "dashboard") renderDashboard();
}
function renderAll(){ render(); }

/* ---------------- rail ---------------- */
function renderRail(){
  // returned-batch workshop select (rebuilt once per state refresh)
  const ws = Object.entries(STATE.workshops || {});
  $("rbWorkshop").innerHTML = ws.map(([id,name]) =>
    `<option value="${id}">${esc(name)} (${id})</option>`).join("");
  const s = STATE;
  const qs = s.queues, max = Math.max(0.1, ...Object.values(qs));
  $("queueDock").innerHTML = `<h3>Live queues</h3>` + Object.entries(qs).sort()
    .map(([w,d]) => `<div class="dock-row"><span style="min-width:34px">${w}</span>
      <span class="qbar-track"><span class="qbar-fill qbar-now" style="width:${(100*d/max).toFixed(1)}%"></span></span>
      <span class="days">${d.toFixed(1)}d</span></div>`).join("")
    + `<div class="muted" style="margin-top:4px">live · ${s.shared?"shared db":"sandbox"}</div>`;
  const objs = ["lateness","defects","hybrid","cost"];
  $("objDock").innerHTML = `<h3>Re-rank objective</h3><div class="obj-grid">` +
    objs.map(o => `<button class="small" style="${o===s.objective?"border-color:var(--blue-deep);color:var(--blue-deep);font-weight:700":""}"
      onclick="setObjective('${o}')">${o}</button>`).join("") + `</div>
    <div class="row" style="margin-top:6px"><button class="small" onclick="rerankAll()">Re-rank all (${s.objective})</button></div>`;
  const shock = STATE.shock_target;
  const shockName = shock && STATE.workshops[shock] ? STATE.workshops[shock] : shock;
  $("worldDock").innerHTML = `<h3>World &amp; shock</h3>
    <div class="row"><select id="asOfSel" onchange="worldSwitch()">
      <option value="2026-04-01" ${STATE.as_of==="2026-04-01"?"selected":""}>April 1st · demo inbox</option>
      <option value="2026-01-01" ${STATE.as_of==="2026-01-01"?"selected":""}>January 1st · full replay</option></select>
      <label class="muted"><input type="checkbox" id="stagesSel" ${STATE.stages?"checked":""} onchange="worldSwitch()"> stages</label></div>
    ${shock ? `<div class="warn">${icon("zap")}${esc(shockName)} is SUSPENDED (seed ${STATE.shock_seed})</div>
      <div class="row"><button class="small" onclick="shockOff()">${icon("check")}Resolve shock</button></div>`
    : `<div class="row"><input id="shockSeed" type="number" value="${STATE.shock_seed||5105}" style="width:80px">
      <button class="small" onclick="shockOn()">${icon("zap")}Trigger</button></div>`}`;
}
async function setObjective(o){ STATE = await post("/api/rerank", {objective:o}); render(); }
async function rerankAll(){ setObjective($("#objDock") ? STATE.objective : "hybrid"); }
async function worldSwitch(){
  status("Rebuilding desk…");
  STATE = await post("/api/world", {as_of:$("asOfSel").value, stages:$("stagesSel").checked});
  render(); status("");
}
async function shockOn(){ STATE = await post("/api/shock", {seed:+($("shockSeed").value||5105)}); render(); }
async function shockOff(){ STATE = await del("/api/shock"); render(); }

/* ---------------- KPI + filters ---------------- */
function pendingCounts(){
  const c = {};
  for (const d of STATE.decisions){
    if (d.skipped || d.already_committed) continue;
    const k = caseOf(d); c[k] = (c[k]||0)+1;
  }
  return c;
}
function renderKpis(){
  const ds = STATE.decisions;
  const open = ds.filter(d => !d.skipped && !d.already_committed);
  const committed = STATE.decisions.filter(d => d.already_committed).length;
  const risk = STATE.at_risk.n_at_risk || 0;
  const totalQ = Object.values(STATE.queues).reduce((a,b)=>a+b,0);
  $("kpis").innerHTML = [
    ["Needs you", open.filter(d=>NEEDS_HUMAN.has(d.behaviour)).length, "needs"],
    ["To confirm", open.filter(d=>d.behaviour==="allocate").length, "confirm"],
    ["Committed", committed, "committed"],
    ["Total queue (days)", totalQ.toFixed(1), "queue"],
    ["At risk", risk, "risk"],
  ].map(([k,v,c]) => `<div class="kpi ${c}"><div class="v">${v}</div><div class="k">${k}</div></div>`).join("");
  const pc = pendingCounts();
  $("caseFilter").innerHTML = ["allocate","refuse","impossible","ask","no_data"].map(b =>
    `<button class="small case-${b} ${CASE===b?"primary":""}" onclick="setCase('${b}')">${BADGE[b][0]} (${pc[b]||0})</button>`).join("");
}
function setCase(b){ CASE = b; renderWorklist(); }

/* ---------------- worklist ---------------- */
function renderWorklist(){
  // preserve which "other option" panels are open across the re-render
  const openDetails = [...document.querySelectorAll("#worklist details[open][data-keep-open]")]
    .map(el => el.dataset.keepOpen);
  const shown = STATE.decisions.filter(d => caseOf(d) === CASE);
  $("worklist").innerHTML = `<div class="muted" style="margin:4px 0">${BADGE[CASE][0]} · ${shown.length} request(s)</div>`
    + shown.map(cardHtml).join("");
  for (const key of openDetails){
    const el = document.querySelector(`details[data-keep-open="${key}"]`);
    if (el) el.open = true;
  }
}
function chatHtml(d){
  const msgs = d.chat || [];
  return msgs.map(m =>
    `<div class="chat-msg ${m.who==="you"?"me":""}"><span class="who">${m.who==="you"?"you":"desk"}:</span> ${esc(m.text)}</div>`
  ).join("");
}
function cardHtml(d){
  const [label, color] = BADGE[d.behaviour] || BADGE.no_data;
  const qs = STATE.queues;
  const live = id => qs[id] ?? 0;
  const scale = Math.max(0.1, ...d.candidates.map(c => live(c.workshop_id) + (c.work_days||0)));
  let body = "";
  if (d.already_committed)
    body += `<div class="muted">Already committed — no further commit possible for this order.</div>`;
  else if (!d.skipped) {
    body += d.candidates.slice(0,3).map(c => {
      const now = live(c.workshop_id), add = c.work_days||0;
      const chosenCls = (d.chosen === c.workshop_id && d.recommended_split == null) ? " chosen" : "";
      return `<div class="cand${chosenCls}" onclick="confirmCard('${d.decision_id}','${c.workshop_id}')">
        <div class="one-line"><b>${esc(c.name)} (${c.workshop_id})</b>${chosenCls?`<span class="rec">${icon("star")}recommended</span>`:""}</div>
        <div class="qbar-track"><span class="qbar-fill qbar-now" style="width:${(100*now/scale).toFixed(1)}%"></span><span class="qbar-fill qbar-add" style="width:${(100*add/scale).toFixed(1)}%"></span></div>
        <div class="meta">queue ${now.toFixed(1)}d${add?` + ${add.toFixed(1)}d`:""} · finish ${c.estimated_finish} · cost ${c.cost.toFixed(2)} · defect ${c.defect_risk.toFixed(2)}</div></div>`;
    }).join("");
    body += (d.splits||[]).map((sp,i) => {
      const star = i === d.recommended_split ? ` <span class="rec">${icon("star")}recommended</span>` : "";
      const parts = sp.parts.map(p => `<div class="split-part"><div class="meta">${p.pieces} pcs · ${esc(p.name)} (${p.workshop_id}) · queue ${live(p.workshop_id).toFixed(1)}d</div></div>`).join("");
      return `<div class="cand" onclick="confirmSplit('${d.decision_id}',${i})">
        <div class="one-line"><b>#${i+1} · ${sp.n_shops} workshops</b>${star}</div>${parts}
        <div class="meta">finish ${sp.earliest_finish} (${sp.meets_due?"on time":sp.days_late+"d late"}) · cost ${sp.cost.toFixed(2)} · defect ${sp.defect_risk.toFixed(2)}</div></div>`;
    }).join("");
  }
  const actions = d.already_committed ? "" : `
    <div class="row">
      <button class="small" onclick="rerank('${d.decision_id}')">${icon("refresh")}Re-rank</button>
      <button class="small" onclick="dismiss('${d.decision_id}')">${icon("trash")}Dismiss</button>
      ${d.skipped ? "" : `<button class="small" onclick="skipCard('${d.decision_id}')">${icon("skip")}Skip</button>`}
    </div>`;
  return `<div class="card ${d.already_committed||d.skipped?"done":""}" id="card-${d.decision_id}">
    <span class="chip ${d.behaviour}" style="background:${color}">${label}</span>
    ${d.order_id ? ` <b>${esc(d.order_id)}</b>` : ""}
    ${d.skipped ? ' <span class="muted">(skipped)</span>' : ""}
    <div class="muted" style="margin:4px 0">${esc(d.explanation)}</div>
    ${(d.warnings||[]).map(w=>`<div class="warn">${icon("alert")}${esc(w)}</div>`).join("")}
    ${body}${actions}
    <details data-keep-open="fu-${d.decision_id}"><summary>Other option (tell me)</summary>
      <div class="chat-box" id="chat-${d.decision_id}">${chatHtml(d)}</div>
      <div class="row"><input id="fu-${d.decision_id}" placeholder="why not W4? / commit to W2 / yes" style="flex:1">
      <button class="small" onclick="followup('${d.decision_id}')">Send</button></div>
    </details>
    <details><summary>tool log (${(d.tool_log||[]).length})</summary>
      <div style="margin-top:4px">${(d.tool_log||[]).map(t=>`<code>${esc(t.tool)}</code>`).join(" ")}</div></details>
  </div>`;
}

/* ---------------- icon system (no emoji; configurable) ---------------- */
const ICONS = {
  play: '<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><polygon points="6 3 20 12 6 21"/></svg>',
  check: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><polyline points="4 12.5 9.5 18 20 6"/></svg>',
  list: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><circle cx="4" cy="6" r="1.4" fill="currentColor"/><circle cx="4" cy="12" r="1.4" fill="currentColor"/><circle cx="4" cy="18" r="1.4" fill="currentColor"/></svg>',
  calendar: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="3" y="4" width="18" height="17" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>',
  refresh: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="21 12 21 17 16 17"/><polyline points="3 12 3 7 8 7"/><path d="M21 7a9 9 0 0 0-15-4L3 6"/><path d="M3 17a9 9 0 0 0 15 4l3-3"/></svg>',
  trash: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/></svg>',
  skip: '<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 4 15 12 5 20"/><line x1="19" y1="5" x2="19" y2="19" stroke="currentColor" stroke-width="2"/></svg>',
  zap: '<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><polygon points="13 2 4 14 11 14 10 22 20 9 12 9 13 2"/></svg>',
  star: '<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><polygon points="12 2 15.1 8.3 22 9.3 17 14.1 18.2 21 12 17.8 5.8 21 7 14.1 2 9.3 8.9 8.3"/></svg>',
  alert: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 3 L22 20 H2 Z"/><line x1="12" y1="10" x2="12" y2="14.5"/><circle cx="12" cy="17.2" r="0.6" fill="currentColor"/></svg>',
};
function icon(name){ return `<span class="icon">${ICONS[name]||""}</span>`; }

/* ---------------- intake & dispatch ---------------- */
async function loadSamples(){
  const names = await api("/api/samples");
  $("sampleSel").innerHTML = names.map(n => `<option>${n}</option>`).join("");
}
async function loadSample(){
  const r = await api("/api/sample?name=" + encodeURIComponent($("sampleSel").value));
  if (r.text) $("inbox").value = r.text;
}
async function uploadFile(ev){
  const f = ev.target.files[0]; if (!f) return;
  $("inbox").value = await f.text();
}
async function doDispatch(){
  const text = $("inbox").value.trim();
  if (!text){ status("Paste a message first."); return; }
  $("dispatchBtn").disabled = true;
  // per-line dispatch: real per-message progress instead of one opaque wait
  const {lines} = await post("/api/split", {text});
  const total = Math.max(1, lines.length);
  $("dispatchProgress").style.display = "";
  try {
    for (let i = 0; i < lines.length; i++){
      $("progressLabel").textContent = `Dispatching ${i+1}/${total} · ${lines[i].slice(0,48)}…`;
      $("progressFill").style.width = `${(100*i/total).toFixed(0)}%`;
      STATE = await post("/api/dispatch", {text: lines[i]});
      render();
    }
    $("progressFill").style.width = "100%";
    $("progressLabel").textContent = `Done — ${total} request(s) dispatched.`;
  } catch(e){
    $("progressLabel").textContent = "Dispatch failed: " + e;
  }
  setTimeout(() => { $("dispatchProgress").style.display = "none"; }, 2500);
  $("dispatchBtn").disabled = false;
}
async function parseMessage(){
  const text = $("parserBox").value.trim();
  if (!text){ status("Type a message to parse."); return; }
  status("Parsing…");
  const r = await post("/api/parse", {text});
  $("parseResult").innerHTML = r.error ? `<div class="warn">${esc(r.error)}</div>`
    : `<pre>${esc(JSON.stringify(r, null, 2))}</pre>
       <button class="primary" onclick="dispatchParsed()">Dispatch this message</button>`;
  window._parsedText = r.error ? null : text;
  status("");
}
async function dispatchParsed(){
  if (!window._parsedText) return;
  $("inbox").value = window._parsedText;
  switchTab("desk"); doDispatch();
}

/* ---------------- confirm family ---------------- */
async function confirmCard(id, wid){
  status("Committing…");
  STATE = await post("/api/confirm", {decision_id:id, workshop_id:wid});
  render(); status("");
}
async function confirmSplit(id, i){
  status("Committing split…");
  STATE = await post("/api/confirm_split", {decision_id:id, index:i});
  render(); status("");
}
async function confirmAllOpen(){
  const n = STATE.decisions.filter(d=>!d.skipped&&!d.already_committed&&d.behaviour==="allocate"&&d.chosen).length;
  if (!n){ status("Nothing to confirm."); return; }
  if (!confirm(`Commit the recommended workshop for all ${n} open allocation(s)?`)) return;
  STATE = await post("/api/confirm_all", {});
  render(); status("Batch confirm done.");
}
async function skipCard(id){ STATE = await post("/api/skip", {decision_id:id}); render(); }
async function dismiss(id){ STATE = await post("/api/dismiss", {decision_id:id}); render(); }
async function rerank(id){ STATE = await post("/api/rerank", {decision_id:id, objective:STATE.objective}); render(); }
let _fuStream = null;
async function followup(id){
  const box = $("fu-"+id), text = box.value.trim();
  if (!text) return;
  box.value = ""; status("Working…");
  const r = await post("/api/followup", {decision_id:id, text});
  if (r.error){ status(r.error); return; }
  STATE = r; render();
  status("");
  // stream the reply into the card's chat area (it persists server-side now)
  const log = $("chat-"+id);
  const reply = r.reply || "";
  if (log && reply){
    const el = document.createElement("div");
    el.className = "chat-msg";
    el.innerHTML = `<span class="who">desk:</span> <span class="stream"></span>`;
    log.appendChild(el);
    const out = el.querySelector(".stream");
    let n = 0;
    clearInterval(_fuStream);
    _fuStream = setInterval(() => {
      n += Math.max(2, Math.round(reply.length / 40));
      out.textContent = reply.slice(0, n);
      log.scrollTop = log.scrollHeight;
      if (n >= reply.length){ out.textContent = reply; clearInterval(_fuStream); }
    }, 25);
  }
}

/* ---------------- scenario ---------------- */
async function runScenario(){
  const body = {
    order_id: $("scOrder").value.trim() || "ORD-063",
    preview_date: $("scDate").value || null,
    closed: $("scClosed").checked,
    delay: +$("scDelay").value || 0,
    noise_pct: +$("scNoise").value || 0,
    seed: +$("scSeed").value || 5105,
    objective: STATE.objective,
  };
  status("Computing…");
  const r = await post("/api/scenario", body);
  if (r.error){
    $("scResult").innerHTML = `<div class="warn">${esc(r.error)}</div>`;
    status(""); return;
  }
  // full queue table per the py version's dataframe: baseline vs scenario ETA,
  // turnaround, sunday pause, transport, late days — with the queue column
  // from the live queues (shock effects visible there)
  const rows = r.baseline.map((b,i) => {
    const a = r.scenario[i];
    const q = STATE.queues[b.workshop_id] ?? 0;
    return `<tr>
      <td><b>${esc(a.name)}</b> <span class="muted">(${a.workshop_id})</span></td>
      <td>${q.toFixed(1)}d</td>
      <td>${b.estimated_finish}</td>
      <td>${a.estimated_finish}</td>
      <td>${a.est_finish_days.toFixed(1)}</td>
      <td>${a.sunday_pause_days}</td>
      <td>${body.delay}</td>
      <td>${a.days_late > 0 ? `<span class="warn">${a.days_late}d late</span>` : `<span class="ok">on time</span>`}</td>
    </tr>`;
  }).join("");
  $("scResult").innerHTML = `
    <div class="muted" style="margin:4px 0">Simulated date: ${esc(r.start_date)} · Objective: ${esc(body.objective)}
      · Baseline pick: <b>${esc(r.baseline_pick.name)}</b> · Scenario pick: <b>${esc(r.scenario_pick.name)}</b></div>
    <table class="sc-table">
      <thead><tr><th>Workshop</th><th>Queue</th><th>Baseline ETA</th><th>Scenario ETA</th>
        <th>Turnaround (d)</th><th>Sun pause</th><th>Transport</th><th>Late</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <div class="muted">${esc(r.scenario_pick.name)} recommended — est. delivery ${esc(r.scenario_pick.estimated_finish)},
      ${r.scenario_pick.days_late} late day(s), cost ${r.scenario_pick.cost.toFixed(2)},
      defect ${(r.scenario_pick.defect_risk*100).toFixed(1)}%.</div>`;
  status("");
}

/* ---------------- records ---------------- */
async function renderRecords(){
  const r = STATE;
  $("recordsShared").textContent = r.shared ? "shared database" : "local sandbox";
  $("shareBtn").textContent = r.shared ? "Disconnect (sandbox)" : "Reset & connect to shared DB";
  const recs = await api("/api/records");
  $("recordsList").innerHTML = recs.length ? recs.map(x =>
    `<div class="card"><b>${esc(x.record_id)}</b> · ${esc(x.order_id)} → ${esc(x.workshop_id)} (${x.pieces} pcs)<br>
     <span class="muted">${esc(x.committed_by)} · ${esc(x.committed_at)} · queue ${x.queue_before} → ${x.queue_after} d</span></div>`)
    .reverse().join("") : '<span class="muted">No committed records yet.</span>';
}
async function shareToggle(){
  if (!confirm(STATE.shared ? "Back to sandbox (session state resets)?"
                            : "Reset this session and connect to the SHARED database?")) return;
  STATE = await post("/api/share", {shared: !STATE.shared});
  render(); status(STATE.shared ? "Connected to the shared database." : "Back in sandbox.");
}
async function resetDemo(){
  if (!confirm("Archive allocations and wipe learned performance?")) return;
  STATE = await post("/api/reset", {});
  render(); status("Reset done.");
}

/* ---------------- left rail: chat log + returned batch ---------------- */
let _seenChats = 0, _streamTimer = null;
function renderChatLog(){
  const log = STATE.chat_log || [];
  const isNew = log.length > _seenChats;
  $("chatLog").innerHTML = log.length ? log.map((e,i) => {
    const oid = (e.text.match(/ORD-\d+/)||[null])[0];
    const fresh = isNew && i === log.length - 1;
    return `<div class="chat-msg ${fresh?"fresh":""}" data-oid="${oid||""}" onclick="locateCard('${oid||""}')">
      <span class="who">${esc(e.speaker)}:</span> ${esc(e.text)}
      <div class="muted reply-text" data-full="${esc(e.reply||"")}">${fresh?"":esc(e.reply||"")}</div></div>`;
  }).join("") : '<span class="muted">No exchanges yet.</span>';
  _seenChats = log.length;
  // stream-render the newest reply: reveal it progressively like a typewriter
  const fresh = $("chatLog").querySelector(".fresh .reply-text");
  if (fresh){
    const full = fresh.dataset.full;
    let n = 0;
    clearInterval(_streamTimer);
    _streamTimer = setInterval(() => {
      n += Math.max(2, Math.round(full.length / 40));
      fresh.textContent = full.slice(0, n);
      if (n >= full.length){ fresh.textContent = full; clearInterval(_streamTimer); }
    }, 30);
  }
}
function locateCard(oid){
  if (!oid) return;
  const d = STATE.decisions.find(x => x.order_id === oid);
  if (!d) return;
  const wl = $("worklist");
  wl.scrollTop = 0;               // reset the inner scroll first, then locate
  window.scrollTo({top: 0, behavior: "instant"});
  const el = $("card-"+d.decision_id);
  if (el){
    setTimeout(() => {
      el.scrollIntoView({behavior:"smooth", block:"center"});
      el.style.boxShadow = "0 0 0 2px var(--blue)";
      setTimeout(() => el.style.boxShadow = "", 1600);
    }, 60);
  }
}
async function recordBatch(){
  const body = {workshop_id: $("rbWorkshop").value,
                pieces: +$("rbPieces").value || 1,
                promised: $("rbPromised").value,
                actual: $("rbActual").value};
  if (!body.promised || !body.actual){ $("rbNote").textContent = "Pick both dates."; return; }
  const r = await post("/api/batch", body);
  STATE = r; render();
  $("rbNote").textContent = r.error ? r.error : `Recorded ✓ ${r.batch_note||""}`;
}

/* smooth CSS zoom for charts: scale the image (GPU), pan via the viewport
   scroll — no re-render, no jank, no state drift */
function makeChartZoom(){
  for (const vp of document.querySelectorAll(".chart-viewport")){
    if (vp.__zoom) continue;
    vp.__zoom = true;
    const img = vp.querySelector("img");
    let scale = 1;
    const apply = () => { img.style.transform = `scale(${scale})`; };
    vp.addEventListener("wheel", e => {
      e.preventDefault();
      const f = e.deltaY < 0 ? 1.12 : 1/1.12;
      scale = Math.min(6, Math.max(1, scale * f));
      if (scale === 1){ img.style.transform = ""; vp.scrollTo(0,0); return; }
      // zoom towards the cursor: keep the hovered point stable
      const r = vp.getBoundingClientRect();
      const px = (e.clientX - r.left + vp.scrollLeft) / (r.width * (scale/f));
      const py = (e.clientY - r.top + vp.scrollTop) / (r.height * (scale/f));
      apply();
      vp.scrollLeft = px * r.width * scale - (e.clientX - r.left);
      vp.scrollTop  = py * r.height * scale - (e.clientY - r.top);
    }, {passive:false});
    let drag = null;
    vp.addEventListener("mousedown", e => { drag = {x:e.clientX, y:e.clientY, l:vp.scrollLeft, t:vp.scrollTop}; e.preventDefault(); });
    window.addEventListener("mousemove", e => {
      if (!drag) return;
      vp.scrollLeft = drag.l - (e.clientX - drag.x);
      vp.scrollTop  = drag.t - (e.clientY - drag.y);
    });
    window.addEventListener("mouseup", () => drag = null);
    vp.addEventListener("dblclick", () => { scale = 1; img.style.transform = ""; vp.scrollTo({left:0, top:0, behavior:"smooth"}); });
  }
}

/* ---------------- dashboard (tiles + grid of matplotlib charts) ---------------- */
const TILE_DEFS = [
  ["requests", "Requests"], ["committed", "Committed"], ["pending", "Pending"],
  ["success_rate", "Success %"], ["failure_rate", "Failure %"],
  ["avg_ms", "Avg ms"], ["interactions", "Interactions"],
  ["llm_rounds_today", "LLM today"], ["backlog_days", "Backlog (d)"],
  ["provider", "Provider"], ["model", "Model"],
];
async function renderDashboard(){
  const a = await api("/api/analytics");
  // lens order selector: any open order, not pinned to the first one
  if ($("lensOrder") && !$("lensOrder").dataset.filled){
    const d = await api("/api/dashboard");
    // open orders from decisions + register: use dashboard lens default list
    const orders = (d.lens && d.lens_order) ? [d.lens_order] : [];
    const all = new Set(orders.concat(STATE.decisions.map(x=>x.order_id).filter(Boolean)));
    // fall back: the lens endpoint accepts any open order id; offer a few
    $("lensOrder").innerHTML = [...all].filter(Boolean).map(o =>
      `<option ${o===d.lens_order?"selected":""}>${o}</option>`).join("");
    $("lensOrder").dataset.filled = "1";
  }
  $("statTiles").innerHTML = TILE_DEFS.map(([k,label]) =>
    `<div class="tile"><div class="v">${esc(a.tiles[k] ?? "—")}</div><div class="k">${label}</div></div>`).join("");
  const t = Date.now();   // cache-bust so charts reflect commits immediately
  const order = $("lensOrder") ? $("lensOrder").value : "";
  for (const [id,kind] of [["chartTimeline","timeline"],["chartDist","dist"],
       ["chartLens","lens"],["chartErrors","errors"],
       ["chartCapacity","capacity"],["chartUsage","usage"],["chartMap","map"]]){
    const extra = id === "chartLens" && order ? `&order_id=${order}` : "";
    $(id).src = `/api/chart/${kind}?t=${t}${extra}`;
  }
  makeChartZoom();
}

/* ---------------- provider / model ---------------- */
function renderProvider(){
  const s = STATE;
  $("providerSel").innerHTML = Object.entries(s.providers)
    .map(([k,v]) => `<option value="${k}" ${k===s.provider?"selected":""}>${esc(v.label)}</option>`).join("");
  const models = s.providers[s.provider].models;
  $("modelSel").innerHTML = models.map(m =>
    `<option value="${m[0]}" ${m[0]===s.model?"selected":""}>${esc(m[1])}</option>`).join("");
}
function renderProviderModels(){
  const s = STATE;
  const models = s.providers[$("providerSel").value].models;
  $("modelSel").innerHTML = models.map(m => `<option value="${m[0]}">${esc(m[1])}</option>`).join("");
}
async function providerChanged(){
  status("Switching provider…");
  const r = await post("/api/provider", {provider:$("providerSel").value, model:$("modelSel").value});
  if (r.error){ status(r.error); return; }   // old desk + tiles stay correct
  STATE = r; render(); status("");
}

/* ---------------- tool log overlay ---------------- */
function renderToolLogOverlay(){
  const ds = STATE.decisions.filter(d => (d.tool_log||[]).length);
  $("toollogBody").innerHTML = ds.length ? ds.map(d => {
    const [label,color] = BADGE[d.behaviour] || BADGE.no_data;
    return `<div class="card">
      <div class="one-line"><span class="chip ${d.behaviour}" style="background:${color}">${label}</span>
      <b>${esc(d.order_id || "(no order)")}</b> <span class="muted">· ${d.tool_log.length} call(s)</span></div>
      ${d.tool_log.map(t => `<div class="muted" style="margin-left:10px">· <code>${esc(t.tool)}</code> ${esc(JSON.stringify(t.arguments||{})).slice(0,80)}</div>`).join("")}
    </div>`;
  }).join("") : '<div class="muted">No tool calls yet — dispatch something first.</div>';
}

/* ---------------- tabs / login ---------------- */
function switchTab(t){
  TAB = t;
  for (const x of ["desk","dashboard","records"]){
    $("tab-"+x).style.display = x===t ? "" : "none";
    $("tabbtn-"+x).classList.toggle("active", x===t);
  }
  if (t==="dashboard") renderDashboard();
}
async function login(){
  const r = await post("/api/login", {password:$("pw").value});
  if (r.token){ document.cookie = "auth="+r.token+";path=/"; $("loginOverlay").style.display="none"; init(); }
  else $("pwErr").textContent = r.error || "Wrong password.";
}
async function init(){
  try {
    await loadSamples();
    await refresh();
  } catch (e) {
    $("loginOverlay").style.display = "flex";
  }
}
document.addEventListener("DOMContentLoaded", () => {
  $("dispatchBtn").onclick = doDispatch;
  $("sampleBtn").onclick = loadSample;
  $("fileInput").onchange = uploadFile;
  $("parseBtn").onclick = parseMessage;
  $("loginBtn").onclick = login;
  $("pw").addEventListener("keydown", e => { if (e.key==="Enter") login(); });
  $("shareBtn").onclick = shareToggle;
  $("resetBtn").onclick = resetDemo;
  $("confirmAllBtn").onclick = confirmAllOpen;
  $("scRun").onclick = runScenario;
  $("providerSel").onchange = () => { renderProviderModels(); providerChanged(); };
  $("modelSel").onchange = providerChanged;
  $("toollogBtn").onclick = () => { renderToolLogOverlay(); $("toollogOverlay").style.display = "block"; };
  $("scenarioBtn").onclick = () => { $("scenarioOverlay").style.display = "block"; };
  for (const x of ["desk","dashboard","records"]) $("tabbtn-"+x).onclick = () => switchTab(x);
  $("rbBtn").onclick = recordBatch;
  // non-modal popovers close on any outside click
  document.addEventListener("click", e => {
    for (const id of ["toollogOverlay","scenarioOverlay"]){
      const p = $(id);
      if (p && p.style.display !== "none" && !p.contains(e.target)
          && !e.target.closest("#toollogBtn") && !e.target.closest("#scenarioBtn"))
        p.style.display = "none";
    }
  });
  switchTab("desk");
  // APP_PASSWORD gate: try state first; server hides it when no password is set
  init().catch(() => {});
});
