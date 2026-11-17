/* ---------------- scenario ---------------- */
async function runScenario(){
  const body = {
    order_id: $("scOrder").value.trim() || "ORD-063",
    preview_date: $("scDate").value || null,
    closed: $("scClosed").checked,
    delay: +$("scDelay").value || 0,
    noise_pct: +$("scNoise").value || 0,
    seed: +$("scSeed").value || 5105,
    objective: STATE.objective,
  };
  status("Computing…");
  const r = await post("/api/scenario", body);
  if (r.error){
    $("scResult").innerHTML = `<div class="warn">${esc(r.error)}</div>`;
    status(""); return;
  }
  // full queue table per the py version's dataframe: baseline vs scenario ETA,
  // turnaround, sunday pause, transport, late days — with the queue column
  // from the live queues (shock effects visible there)
  const rows = r.baseline.map((b,i) => {
    const a = r.scenario[i];
    const q = STATE.queues[b.workshop_id] ?? 0;
    return `<tr>
      <td><b>${esc(a.name)}</b> <span class="muted">(${a.workshop_id})</span></td>
      <td>${q.toFixed(1)}d</td>
      <td>${b.estimated_finish}</td>
      <td>${a.estimated_finish}</td>
      <td>${a.est_finish_days.toFixed(1)}</td>
      <td>${a.sunday_pause_days}</td>
      <td>${body.delay}</td>
      <td>${a.days_late > 0 ? `<span class="warn">${a.days_late}d late</span>` : `<span class="ok">on time</span>`}</td>
    </tr>`;
  }).join("");
  $("scResult").innerHTML = `
    <div class="muted" style="margin:4px 0">Simulated date: ${esc(r.start_date)} · Objective: ${esc(body.objective)}
      · Baseline pick: <b>${esc(r.baseline_pick.name)}</b> · Scenario pick: <b>${esc(r.scenario_pick.name)}</b></div>
    <table class="sc-table">
      <thead><tr><th>Workshop</th><th>Queue</th><th>Baseline ETA</th><th>Scenario ETA</th>
        <th>Turnaround (d)</th><th>Sun pause</th><th>Transport</th><th>Late</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <div class="muted">${esc(r.scenario_pick.name)} recommended — est. delivery ${esc(r.scenario_pick.estimated_finish)},
      ${r.scenario_pick.days_late} late day(s), cost ${r.scenario_pick.cost.toFixed(2)},
      defect ${(r.scenario_pick.defect_risk*100).toFixed(1)}%.</div>`;
  status("");
}

