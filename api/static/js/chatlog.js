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
      // auto-follow the stream: keep the newest text in view as it grows
      $("chatLog").scrollTop = $("chatLog").scrollHeight;
      if (n >= full.length){ fresh.textContent = full; clearInterval(_streamTimer); }
    }, 30);
  }
}
function locateCard(oid){
  if (!oid) return;
  // ask/no_data cards often have no order id — fall back to matching the
  // original message text, then any parsed order id appearing in the reply
  let d = STATE.decisions.find(x => x.order_id === oid)
       || STATE.decisions.find(x => (x.msg||"").includes(oid));
  if (!d){
    // last resort: the reply of an ask/no_data card mentions the order
    d = STATE.decisions.find(x => (x.explanation||"").includes(oid));
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

