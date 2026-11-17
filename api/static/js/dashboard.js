/* ---------------- dashboard (tiles + grid of matplotlib charts) ---------------- */
const TILE_DEFS = [
  ["requests", "Requests"], ["committed", "Committed"], ["pending", "Pending"],
  ["success_rate", "Success %"], ["failure_rate", "Failure %"],
  ["avg_ms", "Avg ms"], ["interactions", "Interactions"],
  ["llm_rounds_today", "LLM today"], ["backlog_days", "Backlog (d)"],
  ["provider", "Provider"], ["model", "Model"],
];
async function renderDashboard(){
  const a = await api("/api/analytics");
  // lens order selector: every open order in the register
  if ($("lensOrder") && !$("lensOrder").dataset.filled){
    const orders = await api("/api/orders");
    $("lensOrder").innerHTML = orders.map(o => `<option>${o}</option>`).join("");
    $("lensOrder").dataset.filled = "1";
  }
  $("statTiles").innerHTML = TILE_DEFS.map(([k,label]) =>
    `<div class="tile"><div class="v">${esc(a.tiles[k] ?? "—")}</div><div class="k">${label}</div></div>`).join("");
  const t = Date.now();   // cache-bust so charts reflect commits immediately
  const order = $("lensOrder") ? $("lensOrder").value : "";
  for (const [id,kind] of [["chartTimeline","timeline"],["chartDist","dist"],
       ["chartLens","lens"],["chartErrors","errors"],
       ["chartCapacity","capacity"],["chartUsage","usage"],["chartMap","map"]]){
    const extra = id === "chartLens" && order ? `&order_id=${order}` : "";
    $(id).src = `/api/chart/${kind}?t=${t}${extra}`;
  }
  makeChartZoom();
}

