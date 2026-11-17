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
    objs.map(o => `<button class="small" style="${o===OBJ?"border-color:var(--blue-deep);color:var(--blue-deep);font-weight:700":""}"
      onclick="setObjective('${o}')">${o}</button>`).join("") + `</div>
    <div class="row" style="margin-top:6px"><button class="small" onclick="rerankAll()">Re-rank all (${OBJ})</button></div>`;
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
async function setObjective(o){
  OBJ = o;   // UI truth first — the highlight never snaps back on slow calls
  render();
  STATE = await post("/api/rerank", {objective:o});
  render();
}
async function rerankAll(){ setObjective(OBJ); }
async function worldSwitch(){
  status("Rebuilding desk…");
  STATE = await post("/api/world", {as_of:$("asOfSel").value, stages:$("stagesSel").checked});
  render(); status("");
}
async function shockOn(){ STATE = await post("/api/shock", {seed:+($("shockSeed").value||5105)}); render(); }
async function shockOff(){ STATE = await del("/api/shock"); render(); }

