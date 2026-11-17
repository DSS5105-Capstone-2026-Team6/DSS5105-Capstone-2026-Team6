/* ---------------- dashboard (tiles + Plotly interactive charts) ----------------
   Plotly gives Streamlit-style interaction for free: drag a box to zoom
   (both axes rescale together), drag to pan, double-click to reset. */
const TILE_DEFS = [
  ["requests", "Requests"], ["committed", "Committed"], ["pending", "Pending"],
  ["success_rate", "Success %"], ["failure_rate", "Failure %"],
  ["avg_ms", "Avg ms"], ["interactions", "Interactions"],
  ["llm_rounds_today", "LLM today"], ["backlog_days", "Backlog (d)"],
  ["provider", "Provider"], ["model", "Model"],
];

const BLUE_DEEP = "#1971c2", BLUE = "#339af0", BLUE_SOFT = "#74c0fc",
      BLUE_PALE = "#d0ebff", MUTED = "#868e96";
const PALETTE = [BLUE_DEEP, BLUE, BLUE_SOFT, "#2b8a3e", "#f08c00", "#e8590c", MUTED, "#845ef7"];

const PLOT_CONF = {responsive: true, displaylogo: false,
                   modeBarButtonsToRemove: ["lasso2d", "select2d"]};

function _layout(extra){
  return Object.assign({
    margin: {l: 48, r: 12, t: 10, b: 40},
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: {family: "inherit", size: 11, color: "#1c2b3a"},
    xaxis: {gridcolor: "#e9f2fb", zerolinecolor: "#e9f2fb"},
    yaxis: {gridcolor: "#e9f2fb", zerolinecolor: "#e9f2fb"},
    showlegend: false,
  }, extra || {});
}
function _empty(msg){
  return {data: [], layout: _layout({annotations: [
    {text: msg, x: 0.5, y: 0.5, xref: "paper", yref: "paper",
     showarrow: false, font: {color: MUTED}}]})};
}
function _plot(id, spec){
  const el = $(id);
  if (!el || typeof Plotly === "undefined") return;
  Plotly.react(el, spec.data, spec.layout, PLOT_CONF);
}

/* ---- trace builders: one per chart kind ---- */
const CHART_BUILDERS = {
  timeline(d){
    if (!d.series.length) return _empty("Queue timeline appears after the first commit");
    return {data: d.series.map((s, i) => ({
      x: s.x, y: s.y, name: s.workshop, type: "scatter", mode: "lines",
      line: {shape: "hv", width: 2, color: PALETTE[i % PALETTE.length]}})),
      layout: _layout({showlegend: true,
        legend: {orientation: "h", y: 1.14, font: {size: 9}},
        yaxis: {title: "queue (days)", gridcolor: "#e9f2fb"},
        xaxis: {title: "commits", gridcolor: "#e9f2fb"}})};
  },
  dist(d){
    if (!d.labels.length) return _empty("No decisions yet");
    return {data: [{type: "bar", orientation: "h", x: d.values, y: d.labels,
      marker: {color: d.colors}}],
      layout: _layout({xaxis: {title: "requests", gridcolor: "#e9f2fb"},
        margin: {l: 84, r: 12, t: 10, b: 40}})};
  },
  lens(d){
    if (!d.names.length) return _empty("No candidates");
    const colors = d.ids.map(id => id === d.chosen ? BLUE_DEEP : BLUE_PALE);
    const spec = {data: [{type: "bar", x: d.names, y: d.finish,
      marker: {color: colors}, width: 0.55}],
      layout: _layout({yaxis: {title: "expected finish (days)", gridcolor: "#e9f2fb"}})};
    if (d.due_slack != null){
      spec.layout.shapes = [{type: "line", xref: "paper", x0: 0, x1: 1,
        y0: d.due_slack, y1: d.due_slack,
        line: {color: "#e03131", width: 1.2, dash: "dash"}}];
      spec.layout.annotations = [{text: "due", xref: "paper", x: 1,
        y: d.due_slack, showarrow: false, font: {color: "#e03131", size: 10},
        xanchor: "right", yanchor: "bottom"}];
    }
    return spec;
  },
  errors(d){
    return {data: [{type: "bar", x: d.labels, y: d.values,
      marker: {color: d.colors}}],
      layout: _layout({yaxis: {title: "count", gridcolor: "#e9f2fb"}})};
  },
  capacity(d){
    return {data: [
      {type: "bar", name: "current", x: d.workshops, y: d.current,
       marker: {color: BLUE_DEEP}},
      {type: "bar", name: "profile", x: d.workshops, y: d.profile,
       marker: {color: BLUE_PALE}}],
      layout: _layout({barmode: "group", showlegend: true,
        legend: {orientation: "h", y: 1.14, font: {size: 9}},
        yaxis: {title: "capacity (pcs/day)", gridcolor: "#e9f2fb"}})};
  },
  usage(d){
    if (!d.days.length) return _empty("No API usage recorded");
    return {data: [{type: "scatter", mode: "lines+markers", x: d.days,
      y: d.rounds, fill: "tozeroy", fillcolor: "rgba(208,235,255,.5)",
      line: {color: BLUE_DEEP, width: 2}, marker: {color: BLUE_DEEP}}],
      layout: _layout({yaxis: {title: "LLM rounds", gridcolor: "#e9f2fb"}})};
  },
  map(d){
    const sizes = d.queue.map(q => 12 + 34 * Math.min(1, q / 5));
    return {data: [{type: "scatter", mode: "markers+text", x: d.cost,
      y: d.defect, text: d.workshops, textposition: "top right",
      textfont: {size: 9, color: MUTED},
      marker: {size: sizes, color: BLUE_SOFT, opacity: 0.7,
               line: {color: BLUE_DEEP, width: 1}}}],
      layout: _layout({xaxis: {title: "cost ($/pc)", gridcolor: "#e9f2fb"},
        yaxis: {title: "defect rate", gridcolor: "#e9f2fb"},
        annotations: [{text: "bubble size = live queue (days)", xref: "paper",
          yref: "paper", x: 1, y: 1.06, showarrow: false,
          font: {size: 9, color: MUTED}, xanchor: "right"}]})};
  },
};

async function renderLens(){
  const order = $("lensOrder") ? $("lensOrder").value : "";
  const d = await api("/api/chart_data/lens" + (order ? `?order_id=${order}` : ""));
  if (!d.error) _plot("chartLens", CHART_BUILDERS.lens(d));
}

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
  const kinds = [["chartTimeline","timeline"],["chartDist","dist"],
                 ["chartErrors","errors"],["chartCapacity","capacity"],
                 ["chartUsage","usage"],["chartMap","map"]];
  await Promise.all(kinds.map(async ([id, kind]) => {
    const d = await api("/api/chart_data/" + kind);
    if (!d.error) _plot(id, CHART_BUILDERS[kind](d));
  }));
  await renderLens();
}
