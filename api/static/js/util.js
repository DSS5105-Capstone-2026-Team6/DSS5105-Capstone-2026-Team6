/* Dispatch Desk static UI — all state comes from /api/state after each action. */
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const api = (p, opt) => fetch(p, opt).then(r => r.json());
const post = (p, body) => api(p, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)});
const del = p => fetch(p, {method:"DELETE"}).then(r => r.json());

const BADGE = {allocate:["ALLOCATE","#d3f9d8"],refuse:["REFUSE","#ffe3e3"],
  impossible:["IMPOSSIBLE","#ffe8cc"],ask:["ASK","#d0ebff"],
  answer:["ANSWER","#e9ecef"],no_data:["NO DATA","#e9ecef"]};
const NEEDS_HUMAN = new Set(["ask","refuse","impossible","no_data"]);
let STATE = null, CASE = "allocate", TAB = "desk";
// the user's chosen objective is UI source of truth (never inferred from a
// possibly-stale STATE snapshot); it syncs to the server on every change
let OBJ = "hybrid";

function status(t){ const el=$("status"); if(el) el.textContent = t; }
async function refresh(){ STATE = await api("/api/state"); render(); }
function caseOf(d){ return d.behaviour === "answer" ? "no_data" : d.behaviour; }

