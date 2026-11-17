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

