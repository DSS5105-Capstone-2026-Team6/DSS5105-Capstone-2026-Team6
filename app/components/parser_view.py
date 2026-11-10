"""
components.parser_view — the card view of one LLM parse (the app-side of
desk/llm_parser.py, used by the "LLM parser" inbox tab).

Distinct from the rule-based splitter behind Group chat: one freeform
message goes to the model, which returns structured JSON (orders / intent /
constraints). render_parse_result() turns that JSON into a readable card
view and checks every extracted value against the order register, so the
reader sees at a glance what the model understood, what it left unknown,
and where the message disagrees with the register (e.g. a new deadline).
"""

import html
import json
import re

import streamlit as st

INTENT_STYLE = {   # chip tint per intent, same light family as BADGE
    "allocate": ("#d3f9d8", "ALLOCATE"),
    "query": ("#d0ebff", "QUERY"),
    "constraint": ("#fff3bf", "CONSTRAINT"),
    "risk": ("#ffe8cc", "RISK"),
    "other": ("#e9ecef", "OTHER"),
}
CONSTRAINT_STYLE = {
    "exclude": ("#ffe3e3", "🚫", "Exclude"),
    "objective": ("#d0ebff", "🎯", "Objective"),
    "date_change": ("#ffe8cc", "📅", "Date change"),
    "other": ("#e9ecef", "•", "Other"),
}
# parsed key -> (label, register column)
FIELDS = [("customer", "Customer", "customer"),
          ("product", "Product", "product"),
          ("category", "Category", "category"),
          ("pieces", "Pieces", "pieces"),
          ("due_date", "Due date", "due_date")]

PARSER_CSS = """
<style>
.pr-head { display:flex; align-items:center; gap:10px; margin:10px 0 4px; flex-wrap:wrap; }
.pr-chip { padding:2px 10px; border-radius:10px; font-weight:600; font-size:.85em; }
.pr-order { font-size:1.05em; font-weight:700; color:var(--blue-deep); }
.pr-grid { display:grid; grid-template-columns:repeat(5,minmax(0,1fr));
           gap:6px; margin-top:6px; }
.pr-cell { border:1px solid var(--line); border-radius:10px; padding:5px 9px; background:#fbfdff; }
.pr-cell .k { color:var(--muted); font-size:.75em; text-transform:uppercase; letter-spacing:.03em; }
.pr-cell .v { font-weight:600; }
.pr-cell .v.null { color:#adb5bd; font-weight:400; font-style:italic; }
.pr-cell .reg { font-size:.75em; margin-top:1px; }
.pr-cell.diff { border-color:#ffa94d; background:#fff9f0; }
.pr-ok { color:#2b8a3e; } .pr-warn { color:#d9480f; }
@media (max-width:700px){ .pr-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } }
.pr-cons { display:flex; gap:6px; flex-wrap:wrap; margin-top:4px; }
.pr-con { border-radius:10px; padding:4px 10px; font-size:.88em; }
</style>
"""


def _esc(v):
    return html.escape(str(v))


def _norm(v):
    """'Bright Basics' == 'BrightBasics', 'cardigans' == 'Cardigan'."""
    s = re.sub(r"[^a-z0-9-]", "", str(v).lower())
    return s[:-1] if s.endswith("s") and not s[:-1].isdigit() else s


def _same(parsed, register):
    if parsed in (None, "") or register in (None, ""):
        return None
    return _norm(parsed) == _norm(register)


def _order_card(o, orders):
    oid = o.get("order_id")
    rec = orders.by_id(oid) if (oid and orders is not None) else None
    if not oid:
        status = '<span class="muted">no order id in the message</span>'
    elif rec is None:
        status = '<span class="pr-warn">⚠ not in the order register</span>'
    else:
        status = (f'<span class="pr-ok">✓ in register</span> '
                  f'<span class="muted">· status {_esc(rec.get("status", "?"))}</span>')
    cells = []
    for key, label, col in FIELDS:
        val = o.get(key)
        reg = rec.get(col) if rec else None
        same = _same(val, reg)
        cls = "pr-cell diff" if same is False else "pr-cell"
        shown = (f'<div class="v">{_esc(val)}</div>' if val not in (None, "")
                 else '<div class="v null">not stated</div>')
        note = ""
        if same is True:
            note = '<div class="reg pr-ok">✓ matches register</div>'
        elif same is False:
            note = f'<div class="reg pr-warn">register: {_esc(reg)}</div>'
        elif val in (None, "") and reg not in (None, ""):
            note = f'<div class="reg muted">register: {_esc(reg)}</div>'
        cells.append(f'<div class="{cls}"><div class="k">{label}</div>{shown}{note}</div>')
    title = _esc(oid) if oid else "Unnamed order"
    return (f'<div class="card"><span class="pr-order">{title}</span> &nbsp;{status}'
            f'<div class="pr-grid">{"".join(cells)}</div></div>')


def render_parse_result(result, orders=None):
    """Card view of one parse: intent chip + counts, one card per order
    (fields vs register), constraint chips, raw JSON on demand."""
    st.markdown(PARSER_CSS, unsafe_allow_html=True)
    if "error" in result:
        st.error(result["error"])
        if result.get("raw"):
            with st.expander("Model output"):
                st.code(result["raw"])
        return
    found = result.get("orders") or []
    cons = result.get("constraints") or []
    intent = str(result.get("intent") or "other").lower()
    tint, label = INTENT_STYLE.get(intent, INTENT_STYLE["other"])
    st.markdown(
        f'<div class="pr-head"><span class="pr-chip" style="background:{tint}">'
        f'{label}</span><span class="muted">{len(found)} order ref(s) · '
        f'{len(cons)} constraint(s)</span></div>', unsafe_allow_html=True)
    for o in found:
        st.markdown(_order_card(o, orders), unsafe_allow_html=True)
    if not found:
        st.caption("No order-like content in this message.")
    if cons:
        chips = []
        for c in cons:
            tint, emo, name = CONSTRAINT_STYLE.get(c.get("type"), CONSTRAINT_STYLE["other"])
            by = f' <span class="muted">— {_esc(c["imposed_by"])}</span>' if c.get("imposed_by") else ""
            chips.append(f'<span class="pr-con" style="background:{tint}">{emo} '
                         f'<b>{name}:</b> {_esc(c.get("detail", ""))}{by}</span>')
        st.markdown(f'<div class="pr-cons">{"".join(chips)}</div>', unsafe_allow_html=True)
    with st.expander("Raw JSON"):
        st.code(json.dumps(result, indent=2, ensure_ascii=False), language="json")
