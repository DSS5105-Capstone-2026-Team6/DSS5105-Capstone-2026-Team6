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
function setCase(b){
  CASE = b;
  renderKpis();      // one entry point for chip state: every path re-renders both
  renderWorklist();
}

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
        <div class="one-line"><span class="chip split">SPLIT #${i+1}</span><b>${sp.n_shops} workshops</b>${star}</div>${parts}
        <div class="meta">finish ${sp.earliest_finish} (${sp.meets_due?"on time":sp.days_late+"d late"}) · cost ${sp.cost.toFixed(2)} · defect ${sp.defect_risk.toFixed(2)}</div></div>`;
    }).join("");
  }
  // skip/dismiss stay available even on already-committed cards (they close
  // the request; only committing is blocked); re-rank needs live candidates
  const actions = `
    <div class="row">
      ${!d.already_committed && d.candidates.length ? `<button class="small" onclick="rerank('${d.decision_id}')">${icon("refresh")}Re-rank</button>` : ""}
      <button class="small" onclick="dismiss('${d.decision_id}')">${icon("trash")}Dismiss</button>
      ${d.skipped ? "" : `<button class="small" onclick="skipCard('${d.decision_id}')">${icon("skip")}Skip</button>`}
    </div>`;
  // request provenance: #N, sender, pieces / due — and the full original
  // text for plain chat input (JSON-parsed lines stay off the card)
  const metaBits = [d.sender,
                    d.pieces ? `${d.pieces} pcs` : null,
                    d.due_date ? `due ${d.due_date}` : null].filter(Boolean);
  const metaLine = (d.req_n || metaBits.length)
    ? `<div class="meta" style="margin-top:2px">${d.req_n ? `<span class="req-link" title="locate in chat log" onclick="locateChat('${d.decision_id}')">Request #${d.req_n}</span>${metaBits.length ? " · " : ""}` : ""}${esc(metaBits.join(" · "))}</div>` : "";
  const rawMsg = d.msg && !d.msg.trim().startsWith("{")
    ? `<div class="req-raw">${esc(d.msg)}</div>` : "";
  return `<div class="card ${d.already_committed||d.skipped?"done":""}" id="card-${d.decision_id}">
    <span class="chip ${d.behaviour}" style="background:${color}">${label}</span>
    ${d.order_id ? ` <b>${esc(d.order_id)}</b>` : ""}
    ${d.skipped ? ' <span class="muted">(skipped)</span>' : ""}
    ${metaLine}${rawMsg}
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

