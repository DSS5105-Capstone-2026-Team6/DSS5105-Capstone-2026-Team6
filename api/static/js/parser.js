/* ---------------- LLM parser popover ----------------
   Card view of one parse, mirroring app/components/parser_view.py:
   intent chip, one card per order (parsed fields vs the register),
   constraint chips, raw JSON on demand. The server attaches the
   register row to each parsed order (`register` key). */

const INTENT_STYLE = {
  allocate:   ["#d3f9d8", "ALLOCATE"],
  query:      ["#d0ebff", "QUERY"],
  constraint: ["#fff3bf", "CONSTRAINT"],
  risk:       ["#ffe8cc", "RISK"],
  other:      ["#e9ecef", "OTHER"],
};
const CONSTRAINT_STYLE = {
  exclude:     ["#ffe3e3", "Exclude"],
  objective:   ["#d0ebff", "Objective"],
  date_change: ["#ffe8cc", "Date change"],
  other:       ["#e9ecef", "Other"],
};
const PARSE_FIELDS = [["customer","Customer"],["product","Product"],
                      ["category","Category"],["pieces","Pieces"],
                      ["due_date","Due date"]];

function _norm(v){
  let s = String(v).toLowerCase().replace(/[^a-z0-9-]/g, "");
  return s.endsWith("s") && !/^\d+$/.test(s.slice(0,-1)) ? s.slice(0,-1) : s;
}
function _same(parsed, register){
  if (parsed == null || parsed === "" || register == null || register === "") return null;
  return _norm(parsed) === _norm(register);
}

function _orderRow(o){
  const oid = o.order_id, rec = o.register;
  const status = !oid ? '<span class="muted">no id</span>'
    : rec ? '<span class="pr-ok">✓ register</span>'
    : '<span class="pr-warn">⚠ not in register</span>';
  const bits = [o.pieces && `${o.pieces} pcs`, o.product,
                o.customer && `for ${o.customer}`,
                o.due_date && `due ${o.due_date}`].filter(Boolean);
  // field-level disagreements with the register, compact ("due→register 04-09")
  const diffs = PARSE_FIELDS
    .filter(([k]) => _same(o[k], rec ? rec[k] : null) === false)
    .map(([k, label]) => `${label.toLowerCase()}→register ${rec[k]}`);
  return `<div class="pr-row"><b>${esc(oid || "new order")}</b> ${status} ` +
    `<span class="muted">${esc(bits.join(" · "))}</span>` +
    (diffs.length ? ` <span class="pr-warn">${esc(diffs.join(", "))}</span>` : "") +
    `</div>`;
}

function renderParseResult(r){
  if (r.error) return `<div class="warn">${esc(r.error)}</div>`;
  const found = r.orders || [], cons = r.constraints || [];
  const intent = String(r.intent || "other").toLowerCase();
  const [tint, label] = INTENT_STYLE[intent] || INTENT_STYLE.other;
  let html = `<div class="pr-head"><span class="pr-chip" style="background:${tint}">${label}</span>
    <span class="muted">${found.length} order ref(s) · ${cons.length} constraint(s)</span></div>`;
  html += found.length ? found.map(_orderRow).join("")
                       : '<div class="muted">No order-like content in this message.</div>';
  if (cons.length){
    html += '<div class="pr-cons">' + cons.map(c => {
      const [t, name] = CONSTRAINT_STYLE[c.type] || CONSTRAINT_STYLE.other;
      const by = c.imposed_by ? ` <span class="muted">— ${esc(c.imposed_by)}</span>` : "";
      return `<span class="pr-con" style="background:${t}"><b>${name}:</b> ${esc(c.detail || "")}${by}</span>`;
    }).join("") + "</div>";
  }
  if (r.normalized && r.normalized.length)
    html += `<div class="pr-normalized"><div class="k muted">Dispatch will send — ${r.normalized.length} request(s), one per line</div>
      <pre class="v">${esc(r.normalized.join("\n"))}</pre></div>`;
  html += `<details style="margin-top:8px"><summary class="muted">Raw JSON</summary>
    <pre>${esc(JSON.stringify(r, null, 2))}</pre></details>
    <div class="row" style="margin-top:8px"><button class="primary" onclick="dispatchParsed()">Dispatch this message</button></div>`;
  return html;
}

async function parseMessage(){
  const text = $("parserBox").value.trim();
  if (!text){ status("Type a message to parse."); return; }
  $("parseBtn").disabled = true;
  $("parseResult").innerHTML = '<div class="muted">Parsing…</div>';
  try {
    const r = await post("/api/parse", {text});
    $("parseResult").innerHTML = renderParseResult(r);
    // dispatch the parsed requests (one JSON line per order), else raw text
    window._parsedText = r.error ? null
      : (r.normalized && r.normalized.length ? r.normalized.join("\n") : text);
  } catch(e){
    $("parseResult").innerHTML = `<div class="warn">Parse failed: ${esc(e)}</div>`;
    window._parsedText = null;
  }
  $("parseBtn").disabled = false;
  status("");
}
async function dispatchParsed(){
  if (!window._parsedText) return;
  $("inbox").value = window._parsedText;
  $("parserOverlay").style.display = "none";
  switchTab("desk"); doDispatch();
}
