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
  renderRail(); renderKpis(); renderWorklist(); renderRecords(); renderDashboardLink();
}
function renderAll(){ render(); }

/* ---------------- rail ---------------- */
function renderRail(){
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
  $("worldDock").innerHTML = `<h3>World &amp; shock</h3>
    <div class="row"><select id="asOfSel" onchange="worldSwitch()">
      <option value="2026-04-01">April 1st · demo inbox</option>
      <option value="2026-01-01">January 1st · full replay</option></select>
      <label class="muted"><input type="checkbox" id="stagesSel" onchange="worldSwitch()"> stages</label></div>
    <div class="row"><input id="shockSeed" type="number" value="5105" style="width:80px">
      <button class="small" onclick="shockOn()">⚡ Trigger</button>
      <button class="small" onclick="shockOff()">Resolve</button></div>`;
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
  const shown = STATE.decisions.filter(d => caseOf(d) === CASE);
  $("worklist").innerHTML = `<div class="muted" style="margin:4px 0">${BADGE[CASE][0]} · ${shown.length} request(s)</div>`
    + shown.map(cardHtml).join("");
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
        <div class="one-line"><b>${esc(c.name)} (${c.workshop_id})</b>${chosenCls?'<span class="rec">⭐ recommended</span>':""}</div>
        <div class="qbar-track"><span class="qbar-fill qbar-now" style="width:${(100*now/scale).toFixed(1)}%"></span><span class="qbar-fill qbar-add" style="width:${(100*add/scale).toFixed(1)}%"></span></div>
        <div class="meta">queue ${now.toFixed(1)}d${add?` + ${add.toFixed(1)}d`:""} · finish ${c.estimated_finish} · cost ${c.cost.toFixed(2)} · defect ${c.defect_risk.toFixed(2)}</div></div>`;
    }).join("");
    body += (d.splits||[]).map((sp,i) => {
      const star = i === d.recommended_split ? ' <span class="rec">⭐ recommended</span>' : "";
      const parts = sp.parts.map(p => `<div class="split-part"><div class="meta">${p.pieces} pcs · ${esc(p.name)} (${p.workshop_id}) · queue ${live(p.workshop_id).toFixed(1)}d</div></div>`).join("");
      return `<div class="cand" onclick="confirmSplit('${d.decision_id}',${i})">
        <div class="one-line"><b>#${i+1} · ${sp.n_shops} workshops</b>${star}</div>${parts}
        <div class="meta">finish ${sp.earliest_finish} (${sp.meets_due?"on time":sp.days_late+"d late"}) · cost ${sp.cost.toFixed(2)} · defect ${sp.defect_risk.toFixed(2)}</div></div>`;
    }).join("");
  }
  const actions = d.already_committed ? "" : `
    <div class="row">
      <button class="small" onclick="rerank('${d.decision_id}')">🔄 Re-rank</button>
      <button class="small" onclick="dismiss('${d.decision_id}')">🗑 Dismiss</button>
      ${d.skipped ? "" : `<button class="small" onclick="skipCard('${d.decision_id}')">⏭ Skip</button>`}
    </div>`;
  return `<div class="card ${d.already_committed||d.skipped?"done":""}" id="card-${d.decision_id}">
    <span class="chip ${d.behaviour}" style="background:${color}">${label}</span>
    ${d.order_id ? ` <b>${esc(d.order_id)}</b>` : ""}
    ${d.skipped ? ' <span class="muted">(skipped)</span>' : ""}
    <div class="muted" style="margin:4px 0">${esc(d.explanation)}</div>
    ${(d.warnings||[]).map(w=>`<div class="warn">⚠ ${esc(w)}</div>`).join("")}
    ${body}${actions}
    <details><summary>Other option (tell me)</summary>
      <div class="chat-box" id="chat-${d.decision_id}"></div>
      <div class="row"><input id="fu-${d.decision_id}" placeholder="why not W4? / commit to W2 / yes" style="flex:1">
      <button class="small" onclick="followup('${d.decision_id}')">Send</button></div>
    </details>
    <details><summary>tool log (${(d.tool_log||[]).length})</summary>
      <div style="margin-top:4px">${(d.tool_log||[]).map(t=>`<code>${esc(t.tool)}</code>`).join(" ")}</div></details>
  </div>`;
}

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
  status("Dispatching… (one LLM round-trip per line)");
  try {
    STATE = await post("/api/dispatch", {text, new_session:false});
    render(); status(`${STATE.decisions.length} request(s) in the worklist.`);
  } catch(e){ status("Dispatch failed: " + e); }
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
async function followup(id){
  const box = $("fu-"+id), text = box.value.trim();
  if (!text) return;
  box.value = ""; status("Working…");
  const r = await post("/api/followup", {decision_id:id, text});
  STATE = r; render();
  const log = $("chat-"+id);
  if (log) log.innerHTML += `<div class="chat-msg"><span class="who">you:</span> ${esc(text)}</div>
    <div class="chat-msg"><span class="who">desk:</span> ${esc(r.reply||"")}</div>`;
  status("");
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
  $("scResult").innerHTML = r.error ? `<div class="warn">${esc(r.error)}</div>` : `
    <div class="muted">Baseline pick: ${esc(r.baseline_pick.name)} · Scenario pick: ${esc(r.scenario_pick.name)}</div>
    <pre>${esc(JSON.stringify(r.scenario.map(x=>({w:x.workshop_id, eta:x.estimated_finish, late:x.days_late})), null, 1))}</pre>`;
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

/* ---------------- dashboard (inline SVG) ---------------- */
function svgEl(w,h,inner){ return `<svg viewBox="0 0 ${w} ${h}" style="width:100%;height:auto">${inner}</svg>`; }
function bars(data, w=560, h=180, colors=["#d0ebff","#1971c2"]){
  if (!data.length) return "";
  const max = Math.max(0.1, ...data.map(d=>d.v));
  const bw = (w-40)/data.length;
  return svgEl(w,h, data.map((d,i)=>{
    const bh = (h-40)*d.v/max;
    return `<rect x="${30+i*bw+4}" y="${h-25-bh}" width="${bw-8}" height="${bh}" rx="3" fill="${d.c||colors[1]}"/>
      <text x="${30+i*bw+bw/2}" y="${h-8}" font-size="9" text-anchor="middle" fill="#868e96">${esc(d.k)}</text>
      <text x="${30+i*bw+bw/2}" y="${h-30-bh}" font-size="9" text-anchor="middle" fill="#1c2b3a">${d.v.toFixed(1)}</text>`;
  }).join(""));
}
function lineChart(points, w=560, h=180){
  if (!points.length) return '<div class="muted">Queue timeline appears after the first commit.</div>';
  const shops = [...new Set(points.map(p=>p.workshop))];
  const max = Math.max(0.1, ...points.map(p=>p.queue));
  const colors = ["#1971c2","#339af0","#74c0fc","#d0ebff","#2b8a3e","#f08c00","#e8590c","#868e96"];
  return svgEl(w,h, shops.map((s,si)=>{
    const pts = points.filter(p=>p.workshop===s);
    const step = pts.map((p,i)=>`${i===0?"M":"L"}${30+i*(w-50)/Math.max(1,points.length/shops.length-1||1)},${h-25-(h-45)*p.queue/max}`).join(" ");
    return `<path d="${step}" fill="none" stroke="${colors[si%8]}" stroke-width="2"/>`;
  }).join("") + shops.map((s,i)=>`<circle cx="${30+i*70}" cy="12" r="4" fill="${colors[i%8]}"/><text x="${38+i*70}" y="15" font-size="9" fill="#1c2b3a">${esc(s)}</text>`).join(""));
}
async function renderDashboard(){
  const d = await api("/api/dashboard");
  $("dashTimeline").innerHTML = `<h3>Queue timeline</h3>` + lineChart(d.timeline);
  const cap = d.capacity.map(c => ({k:c.workshop, v:c.current, c: c.source==="learned"?"#1971c2":c.source==="observing"?"#74c0fc":"#d0ebff"}));
  $("dashCapacity").innerHTML = `<h3>Capacity: profile vs learned</h3>` + bars(cap) +
    `<div class="muted"><span class="legend-dot" style="background:#1971c2"></span>learned <span class="legend-dot" style="background:#74c0fc"></span>observing <span class="legend-dot" style="background:#d0ebff"></span>profile</div>`;
  if (d.lens && d.lens.candidates){
    const rows = d.lens.candidates.map(r => ({k:r.workshop_id, v:r.est_finish_days, c: r.workshop_id===d.lens.chosen?"#1971c2":"#d0ebff"}));
    $("dashLens").innerHTML = `<h3>Allocator lens — ${esc(d.lens_order)}, objective ${esc(STATE.objective)}</h3>` + bars(rows);
  }
  const bs = d.bubbles;
  const maxC = Math.max(0.1,...bs.map(b=>b.cost)), maxD = Math.max(0.1,...bs.map(b=>b.defect)), maxQ = Math.max(0.1,...bs.map(b=>b.queue));
  $("dashMap").innerHTML = `<h3>Objective map — cost × defect (bubble = live queue)</h3>` +
    svgEl(560,220, bs.map(b=>{
      const x=40+480*b.cost/maxC, y=190-160*b.defect/maxD, r=5+14*b.queue/maxQ;
      return `<circle cx="${x}" cy="${y}" r="${r}" fill="#74c0fc" fill-opacity=".7" stroke="#1971c2"/>
              <text x="${x+r+3}" y="${y+3}" font-size="9" fill="#1c2b3a">${esc(b.workshop)}</text>`;
    }).join("") + `<text x="45%" y="215" font-size="9" fill="#868e96">cost ($/pc) →</text>`);
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
  for (const x of ["desk","dashboard","records"]) $("tabbtn-"+x).onclick = () => switchTab(x);
  switchTab("desk");
  // APP_PASSWORD gate: try state first; server hides it when no password is set
  init().catch(() => {});
});
