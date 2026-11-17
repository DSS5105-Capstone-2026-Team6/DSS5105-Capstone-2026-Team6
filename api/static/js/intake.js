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

