/* ---------------- compare models ---------------- */
function fillCompareSelects(){
  const opts = [];
  for (const [prov, spec] of Object.entries(STATE.providers))
    for (const m of spec.models) opts.push(`${prov}:${m[0]}|${spec.label} · ${m[1]}`);
  const html = opts.map(o => {
    const [v, label] = o.split("|");
    return `<option value="${v}">${esc(label)}</option>`;
  }).join("");
  $("cmpA").innerHTML = html; $("cmpB").innerHTML = html;
  if (opts.length > 1) $("cmpB").selectedIndex = 1;
}
async function compareModels(){
  const a = $("cmpA").value, b = $("cmpB").value;
  if (a === b){ $("cmpResult").textContent = "Pick two different models."; return; }
  const n = +$("cmpN").value || 3;
  $("cmpBtn").disabled = true;
  $("cmpResult").textContent = `Running ${n} dev requests per model (LLM rounds)…`;
  const r = await post("/api/compare_models", {models:[a,b], limit:n});
  $("cmpBtn").disabled = false;
  $("cmpResult").innerHTML = r.models.map(m => {
    if (m.error) return `<div class="warn">${esc(m.model)}: ${esc(m.error)}</div>`;
    const rows = m.results.map(x =>
      `<tr><td>${x.id}</td><td>${x.expected||"—"}</td>
       <td style="color:${x.ok?"#2b8a3e":"#e03131"}">${x.got}</td></tr>`).join("");
    return `<div style="margin-bottom:8px"><b>${esc(m.model)}</b>
      <span class="muted"> · accuracy ${m.accuracy ?? "—"}</span>
      <table class="sc-table"><thead><tr><th>req</th><th>expected</th><th>got</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`;
  }).join("");
}

