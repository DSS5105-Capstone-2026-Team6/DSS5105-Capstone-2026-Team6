"""
theme.styles — the global stylesheet (design tokens, cards, buttons, queue
bars, clickable cards, right-rail panels, KPI colours, sticky rail).

One big CSS string injected once by the entry point. Pure text: no imports.
"""

CSS = """
<style>
/* ---------- design tokens ---------- */
:root {
    --blue-deep: #1971c2;
    --blue: #339af0;
    --blue-soft: #74c0fc;
    --blue-pale: #d0ebff;
    --ink: #1c2b3a;
    --muted: #868e96;
    --line: #e3eaf2;
    --shadow-sm: 0 1px 4px rgba(25,113,194,.07);
    --shadow-md: 0 6px 18px rgba(25,113,194,.13);
    --ease: cubic-bezier(.25,.8,.25,1);
}
.block-container {
    max-width: 1200px;
    margin: auto;
    padding-top: 1.6rem;
    color: var(--ink);
}
h1 { font-size: 1.4rem !important; letter-spacing: -0.01em; }

/* ---------- cards ---------- */
.card {
    border: 1px solid var(--line);
    border-radius: 14px;
    padding: 9px 12px; margin: 6px 0;
    background: #fff; font-size: 0.92em;
    box-shadow: var(--shadow-sm);
    transition: transform .25s var(--ease), box-shadow .25s var(--ease),
                border-color .25s var(--ease);
    animation: fadeUp .35s var(--ease) both;
}
.card:hover {
    transform: translateY(-2px);
    box-shadow: var(--shadow-md);
    border-color: var(--blue-soft);
}
.card.chosen { border: 2px solid var(--blue); background: #f1f8fe; }
.muted { color: var(--muted); font-size: 0.85em; }
.field { margin: 1px 0; }
.field b { display: inline-block; min-width: 7em; }

@keyframes fadeUp {
    from { opacity: 0; transform: translateY(8px); }
    to   { opacity: 1; transform: translateY(0); }
}

/* ---------- buttons & controls ---------- */
.stButton > button {
    border-radius: 10px !important;
    border: 1px solid var(--line) !important;
    transition: all .2s var(--ease) !important;
}
.stButton > button:hover {
    border-color: var(--blue) !important;
    box-shadow: var(--shadow-sm) !important;
    transform: translateY(-1px);
}
.stButton > button[kind="primary"] {
    background: var(--blue-deep) !important;
    border-color: var(--blue-deep) !important;
}
[data-testid="stExpander"] {
    border: 1px solid var(--line) !important;
    border-radius: 12px !important;
    box-shadow: var(--shadow-sm);
    transition: box-shadow .25s var(--ease);
}
[data-testid="stExpander"]:hover { box-shadow: var(--shadow-md); }

/* ---------- queue bars ---------- */
.qbar-track {
    display: flex; height: 8px; border-radius: 5px;
    background: #e9ecef; overflow: hidden; margin: 4px 0 3px;
}
.qbar-fill { height: 100%; animation: qgrow .9s var(--ease) both; }
.qbar-now  { background: var(--blue-soft); }
.qbar-add  { background: var(--blue-deep); }
@keyframes qgrow { from { width: 0; } }
.qbar-legend { color: var(--muted); font-size: 0.8em; }

/* ---------- clickable cards (candidates / splits) ----------
   tabs.desk.cards.clickable_card: a keyed container holding the card and a
   transparent st.button stretched over it, so the whole card is the
   button. Hover lifts the card and reveals the "Click to confirm" hint. */
[class*="st-key-pick_"] { position: relative; gap: 0 !important; }
[class*="st-key-pick_"] > [class*="st-key-btn-"] {
    position: absolute !important; inset: 0; z-index: 2; margin: 0;
    width: 100% !important; height: 100%;
}
[class*="st-key-pick_"] .stButton { height: 100%; }
[class*="st-key-pick_"] .stButton > button {
    width: 100%; height: 100%; opacity: 0; cursor: pointer;
}
[class*="st-key-pick_"] { margin: 6px 0; }
[class*="st-key-pick_"] .card { cursor: pointer; margin: 0; }
[class*="st-key-pick_"] .stMarkdown div:has(> .card) { margin-bottom: 0 !important; }
[class*="st-key-pick_"]:hover .card {
    transform: translateY(-2px); box-shadow: var(--shadow-md);
    border-color: var(--blue);
}
.pick-hint {
    font-size: .78em; color: var(--blue-deep); font-weight: 600;
    text-align: right; height: 0; overflow: visible; opacity: 0;
    transform: translateY(-1.25em); transition: opacity .2s var(--ease);
}
[class*="st-key-pick_"]:hover .pick-hint { opacity: 1; }
.card .rec { color: var(--blue-deep); font-size: .82em; font-weight: 600; }
.split-part { margin-top: 6px; }
.split-name { font-size: .88em; }

/* ---------- right-rail panels ---------- */
[class*="st-key-objective_dock"], [class*="st-key-queue_dock"] {
    background: #fff; border: 1px solid var(--line); border-radius: 14px;
    padding: 10px 14px; font-size: 0.85em; margin-bottom: 10px;
    box-shadow: var(--shadow-sm);
    transition: box-shadow .25s var(--ease);
    animation: fadeUp .4s var(--ease) both;
}
[class*="st-key-objective_dock"]:hover, [class*="st-key-queue_dock"]:hover {
    box-shadow: var(--shadow-md);
}
.dock-row { display: flex; align-items: center; gap: 6px; margin: 1px 0; }
.dock-row .qbar-track { flex: 1; margin: 0; height: 7px; }
.dock-row .dock-name { min-width: 86px; }
.dock-row .dock-days { min-width: 36px; text-align: right; color: var(--muted); }

/* objective grid: square boxes, no pill clipping in the narrow rail */
[class*="st-key-objective_dock"] .stButton > button {
    border-radius: 6px !important;
    padding: 2px 6px !important;
    min-height: 34px !important;
    font-size: 0.95em !important;
}

/* content columns: worklist + dashboard stay a comfortable reading width
   instead of stretching across the main area */
[class*="st-key-worklist"], [class*="st-key-dash_body"] { max-width: 740px; }

/* tighter cards: the expander content is information-dense, not airy */
.card { line-height: 1.35; padding: 7px 11px; margin: 4px 0; }
.card .one-line { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }

/* icon chip: blue-white section markers (dashboard, docks, cards) */
.icon-chip {
    display: inline-block; background: var(--blue-pale); border-radius: 7px;
    padding: 3px 5px 1px; margin-right: 2px;
}

/* case filter: each behaviour's button tinted with its own colour — keyed
   containers, because column testids vary between Streamlit versions */
[class*="st-key-case-allocate"] .stButton > button[kind="secondary"] { color: #2b8a3e; border-color: #b2dfbe !important; }
[class*="st-key-case-refuse"] .stButton > button[kind="secondary"] { color: #e03131; border-color: #ffc9c9 !important; }
[class*="st-key-case-impossible"] .stButton > button[kind="secondary"] { color: #e8590c; border-color: #ffd8a8 !important; }
[class*="st-key-case-ask"] .stButton > button[kind="secondary"] { color: #1971c2; border-color: #a5d8ff !important; }
[class*="st-key-case-no_data"] .stButton > button[kind="secondary"] { color: #868e96; border-color: #dee2e6 !important; }
[class*="st-key-case_filter"] .stButton > button { font-weight: 600; border-radius: 8px !important; }

/* section headers: consistent rhythm — roomy above, tight below */
.section-head {
    display: flex; align-items: center; gap: 5px;
    margin: 12px 0 3px; font-weight: 600;
}
.section-head b { font-size: 0.98em; }

/* KPI row: numbers coloured by meaning (keyed containers, version-proof)
   grey needs-you / amber to-confirm / green committed / blue queue / red risk */
[class*="st-key-kpi_needs"] [data-testid="stMetricValue"] { color: #868e96; }
[class*="st-key-kpi_confirm"] [data-testid="stMetricValue"] { color: #f08c00; }
[class*="st-key-kpi_committed"] [data-testid="stMetricValue"] { color: #2b8a3e; }
[class*="st-key-kpi_queue"] [data-testid="stMetricValue"] { color: #1971c2; }
[class*="st-key-kpi_risk"] [data-testid="stMetricValue"] { color: #e03131; }

/* the right rail follows the scroll: sticky COLUMN, the canonical
   Streamlit pattern. Both column testids are listed (the attribute name
   changed between Streamlit versions); scoped to the layout row so the
   KPI/filter columns stay untouched. align-self: flex-start un-stretches
   the column — a stretched column is exactly as tall as the row, which
   leaves sticky no room to travel. */
[class*="st-key-layout"] [data-testid="stColumn"]:nth-of-type(2),
[class*="st-key-layout"] [data-testid="column"]:nth-of-type(2) {
    position: sticky; top: 64px; align-self: flex-start;
}

/* ---------- metrics ---------- */
[data-testid="stMetric"] {
    background: #fff; border: 1px solid var(--line); border-radius: 12px;
    padding: 8px 12px; box-shadow: var(--shadow-sm);
}
[data-testid="stMetricValue"] { color: var(--blue-deep); }

/* ---------- responsive: rail stacks on narrow screens ---------- */
@media (max-width: 900px) {
    .block-container { max-width: 100%; padding-left: .8rem; padding-right: .8rem; }
    [data-testid="stHorizontalBlock"] { flex-wrap: wrap; }
}

/* ---------- scenario popover dock: fixed to the viewport ----------
   position: sticky failed twice inside Streamlit's wrapper DOM (ancestor
   overflow + stretched-column geometry). position: fixed ignores the whole
   ancestor chain. The spacer keeps the button's original layout slot, so
   the intake area below is never covered before the popover opens. */
[class*="st-key-scenario_pop_spacer"] { height: 46px; }
[class*="st-key-scenario_pop"] {
    position: fixed;
    top: 60px;
    z-index: 300;
    /* hug the right edge of the main content block (max-width 1200) */
    right: max(16px, calc((100vw - 1200px) / 2 + 16px));
    width: auto;
    white-space: nowrap;
    background: #fff;
    border: 1px solid var(--line);
    border-radius: 14px;
    padding: 2px 8px;
    box-shadow: var(--shadow-md);
}
/* sidebar expanded: the content block shifts right by 336px (21rem),
   so the right offset shrinks accordingly */
body:has([data-testid="stSidebar"][aria-expanded="true"]) [class*="st-key-scenario_pop"],
body:has([data-testid="stSidebarContent"][aria-expanded="true"]) [class*="st-key-scenario_pop"] {
    right: max(16px, calc((100vw - 1536px) / 2 + 16px));
}
@media (max-width: 900px) {
    [class*="st-key-scenario_pop"] { position: static; width: auto; }
    [class*="st-key-scenario_pop_spacer"] { display: none; }
}

/* ---------- worklist density: tighter request cards ---------- */
[class*="st-key-worklist"] .card {
    padding: 4px 8px; margin: 2px 0;
    line-height: 1.25; font-size: 0.88em;
}
[class*="st-key-worklist"] [data-testid="stExpander"] { margin-bottom: 2px; }
[class*="st-key-worklist"] [data-testid="stExpander"] summary {
    padding-top: 4px !important; padding-bottom: 4px !important;
    min-height: 0 !important;
}
[class*="st-key-worklist"] .stMarkdown p { margin-bottom: 0.2em; }
[class*="st-key-worklist"] .qbar-track { height: 6px; margin: 2px 0; }
[class*="st-key-worklist"] .section-head { margin: 6px 0 2px; }
</style>
"""
