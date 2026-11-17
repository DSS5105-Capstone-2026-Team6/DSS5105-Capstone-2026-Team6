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

function _orderCard(o){
  const oid = o.order_id, rec = o.register;
  let status;
  if (!oid) status = '<span class="muted">no order id in the message</span>';
  else if (!rec) status = '<span class="pr-warn">⚠ not in the order register</span>';
  else status = `<span class="pr-ok">✓ in register</span> <span class="muted">· status ${esc(rec.status || "?")}</span>`;
  const cells = PARSE_FIELDS.map(([key, label]) => {
    const val = o[key], reg = rec ? rec[key] : null;
    const same = _same(val, reg);
    const cls = same === false ? "pr-cell diff" : "pr-cell";
    const shown = (val != null && val !== "")
      ? `<div class="v">${esc(val)}</div>` : '<div class="v null">not stated</div>';
    let note = "";
    if (same === true) note = '<div class="reg pr-ok">✓ matches register</div>';
    else if (same === false) note = `<div class="reg pr-warn">register: ${esc(reg)}</div>`;
    else if ((val == null || val === "") && reg != null && reg !== "")
      note = `<div class="reg muted">register: ${esc(reg)}</div>`;
    return `<div class="${cls}"><div class="k">${label}</div>${shown}${note}</div>`;
  }).join("");
  return `<div class="card"><span class="pr-order">${esc(oid || "Unnamed order")}</span> &nbsp;${status}
    <div class="pr-grid">${cells}</div></div>`;
}

function renderParseResult(r){
  if (r.error) return `<div class="warn">${esc(r.error)}</div>`;
  const found = r.orders || [], cons = r.constraints || [];
  const intent = String(r.intent || "other").toLowerCase();
  const [tint, label] = INTENT_STYLE[intent] || INTENT_STYLE.other;
  let html = `<div class="pr-head"><span class="pr-chip" style="background:${tint}">${label}</span>
    <span class="muted">${found.length} order ref(s) · ${cons.length} constraint(s)</span></div>`;
  html += found.length ? found.map(_orderCard).join("")
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
