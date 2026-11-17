/* ---------------- provider / model ---------------- */
function renderProvider(){
  const s = STATE;
  $("providerSel").innerHTML = Object.entries(s.providers)
    .map(([k,v]) => `<option value="${k}" ${k===s.provider?"selected":""}>${esc(v.label)}</option>`).join("");
  const models = s.providers[s.provider].models;
  $("modelSel").innerHTML = models.map(m =>
    `<option value="${m[0]}" ${m[0]===s.model?"selected":""}>${esc(m[1])}</option>`).join("");
}
function renderProviderModels(){
  const s = STATE;
  const models = s.providers[$("providerSel").value].models;
  $("modelSel").innerHTML = models.map(m => `<option value="${m[0]}">${esc(m[1])}</option>`).join("");
}
async function providerChanged(){
  status("Switching provider…");
  const r = await post("/api/provider", {provider:$("providerSel").value, model:$("modelSel").value});
  if (r.error){ status(r.error); return; }   // old desk + tiles stay correct
  STATE = r; render(); status("");
}

