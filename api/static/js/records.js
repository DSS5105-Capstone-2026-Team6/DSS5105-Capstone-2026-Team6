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

