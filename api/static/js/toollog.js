/* ---------------- tool log overlay ----------------
   Open cards (live) + archived logs of committed/dismissed cards, so a
   commit never makes the trail disappear. Newest first. */
function _toolLogCard(orderId, behaviour, toolLog, tag){
  const [label, color] = BADGE[behaviour] || BADGE.no_data;
  return `<div class="card">
    <div class="one-line"><span class="chip ${behaviour}" style="background:${color}">${label}</span>
    <b>${esc(orderId || "(no order)")}</b> <span class="muted">· ${toolLog.length} call(s) ${tag || ""}</span></div>
    ${toolLog.map(t => `<div class="muted" style="margin-left:10px">· <code>${esc(t.tool)}</code> ${esc(JSON.stringify(t.arguments||{})).slice(0,80)}</div>`).join("")}
  </div>`;
}
function renderToolLogOverlay(){
  const open = STATE.decisions.filter(d => (d.tool_log||[]).length)
    .map(d => _toolLogCard(d.order_id, d.behaviour, d.tool_log, "· open"));
  const hist = (STATE.tool_history || []).slice().reverse()
    .map(h => _toolLogCard(h.order_id, h.behaviour, h.tool_log, "· closed"));
  $("toollogBody").innerHTML = (open.length + hist.length)
    ? open.concat(hist).join("")
    : '<div class="muted">No tool calls yet — dispatch something first.</div>';
}
