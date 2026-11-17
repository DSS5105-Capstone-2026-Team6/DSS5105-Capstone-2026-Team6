/* ---------------- tabs / login ---------------- */
function switchTab(t){
  TAB = t;
  for (const x of ["desk","dashboard","records"]){
    $("tab-"+x).style.display = x===t ? "" : "none";
    $("tabbtn-"+x).classList.toggle("active", x===t);
  }
  if (t==="dashboard") renderDashboard();
}
async function login(){
  const r = await post("/api/login", {password:$("pw").value});
  if (r.token){ document.cookie = "auth="+r.token+";path=/"; $("loginOverlay").style.display="none"; init(); }
  else $("pwErr").textContent = r.error || "Wrong password.";
}
async function init(){
  try {
    await loadSamples();
    await refresh();
    OBJ = STATE.objective || "hybrid";   // adopt server truth once on load
    render();
  } catch (e) {
    $("loginOverlay").style.display = "flex";
  }
}
document.addEventListener("DOMContentLoaded", () => {
  $("dispatchBtn").onclick = doDispatch;
  $("sampleBtn").onclick = loadSample;
  $("fileInput").onchange = uploadFile;
  $("parseBtn").onclick = parseMessage;
  $("loginBtn").onclick = login;
  $("pw").addEventListener("keydown", e => { if (e.key==="Enter") login(); });
  $("shareBtn").onclick = shareToggle;
  $("resetBtn").onclick = resetDemo;
  $("confirmAllBtn").onclick = confirmAllOpen;
  $("scRun").onclick = runScenario;
  $("providerSel").onchange = () => { renderProviderModels(); providerChanged(); };
  $("modelSel").onchange = providerChanged;
  $("toollogBtn").onclick = () => { renderToolLogOverlay(); $("toollogOverlay").style.display = "block"; };
  $("scenarioBtn").onclick = () => { $("scenarioOverlay").style.display = "block"; };
  $("parserBtn").onclick = () => { $("parserOverlay").style.display = "block"; $("parserBox").focus(); };
  for (const x of ["desk","dashboard","records"]) $("tabbtn-"+x).onclick = () => switchTab(x);
  $("rbBtn").onclick = recordBatch;
  $("cmpBtn").onclick = compareModels;
  // non-modal popovers close on any outside click
  document.addEventListener("click", e => {
    for (const id of ["toollogOverlay","scenarioOverlay","parserOverlay"]){
      const p = $(id);
      if (p && p.style.display !== "none" && !p.contains(e.target)
          && !e.target.closest("#toollogBtn") && !e.target.closest("#scenarioBtn")
          && !e.target.closest("#parserBtn"))
        p.style.display = "none";
    }
  });
  switchTab("desk");
  // APP_PASSWORD gate: try state first; server hides it when no password is set
  init().catch(() => {});
});
