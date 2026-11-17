/* ---------------- left rail: chat log + returned batch ---------------- */
let _seenChats = 0, _streamTimer = null;
function renderChatLog(){
  const log = STATE.chat_log || [];
  const isNew = log.length > _seenChats;
  $("chatLog").innerHTML = log.length ? log.map((e,i) => {
    const oid = (e.text.match(/ORD-\d+/)||[null])[0];
    const fresh = isNew && i === log.length - 1;
    const who = e.speaker === "request"
      ? `Request #${e.n}${e.user ? " · " + e.user : ""}`
      : e.speaker;
    return `<div class="chat-msg ${fresh?"fresh":""}" data-did="${e.decision_id||""}" data-oid="${oid||""}" onclick="locateCard('${e.decision_id||""}','${oid||""}')">
      <span class="who">${esc(who)}:</span> ${esc(e.text)}
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
      // auto-follow the stream: keep the newest text in view as it grows
      $("chatLog").scrollTop = $("chatLog").scrollHeight;
      if (n >= full.length){ fresh.textContent = full; clearInterval(_streamTimer); }
    }, 30);
  }
}
function locateCard(did, oid){
  // direct binding first: every chat entry now carries its decision id
  let d = did ? STATE.decisions.find(x => x.decision_id === did) : null;
  if (!d && oid){
    d = STATE.decisions.find(x => x.order_id === oid)
     || STATE.decisions.find(x => (x.msg||"").includes(oid))
     || STATE.decisions.find(x => (x.explanation||"").includes(oid));
  }
  if (!d) return;
  // jump straight to the card's behaviour filter instead of requiring the
  // user to pick it first
  const target = caseOf(d);
  if (target !== CASE){ CASE = target; renderKpis(); renderWorklist(); }
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

