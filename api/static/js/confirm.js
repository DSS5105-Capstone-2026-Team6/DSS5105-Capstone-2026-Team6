/* ---------------- confirm family ---------------- */
async function confirmCard(id, wid){
  status("Committing…");
  if (applyState(await post("/api/confirm", {decision_id:id, workshop_id:wid}))) {
    render();
    setTimeout(refresh, 1500);   // pick up the background star refresh
  }
  status("");
}
async function confirmSplit(id, i){
  status("Committing split…");
  if (applyState(await post("/api/confirm_split", {decision_id:id, index:i}))) { render(); }
  status("");
}
async function confirmAllOpen(){
  const n = STATE.decisions.filter(d=>!d.skipped&&!d.already_committed&&d.behaviour==="allocate"&&d.chosen).length;
  if (!n){ status("Nothing to confirm."); return; }
  if (!confirm(`Commit the recommended workshop for all ${n} open allocation(s)?`)) return;
  if (applyState(await post("/api/confirm_all", {}))) { render(); status("Batch confirm done."); setTimeout(refresh, 1500); }
}
async function skipCard(id){ if (applyState(await post("/api/skip", {decision_id:id}))) render(); }
async function dismiss(id){ if (applyState(await post("/api/dismiss", {decision_id:id}))) render(); }
async function rerank(id){ if (applyState(await post("/api/rerank", {decision_id:id, objective:OBJ}))) render(); }
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

