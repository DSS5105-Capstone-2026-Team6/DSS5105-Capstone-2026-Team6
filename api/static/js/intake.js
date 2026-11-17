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

