"""
ui_shared — constants and leaf helpers shared by every UI module.

Imports only streamlit + desk.contracts (never app.streamlit_app), so every
other app module can import this one safely.
"""

import streamlit as st

from desk.contracts import Behaviour

# behaviour badge chips: text + tint. Semantics come first (green/red/
# orange/blue); everything else in the UI stays in the light-blue family.
# Labels are plain text — the colour does the talking.
BADGE = {
    Behaviour.ALLOCATE: ("ALLOCATE", "#d3f9d8"),
    Behaviour.REFUSE: ("REFUSE", "#ffe3e3"),
    Behaviour.IMPOSSIBLE: ("IMPOSSIBLE", "#ffe8cc"),
    Behaviour.ASK: ("ASK", "#d0ebff"),
    Behaviour.ANSWER: ("ANSWER", "#e9ecef"),
    Behaviour.NO_DATA: ("NO DATA", "#e9ecef"),
}

# ---------- inline SVG icon set (feather-style, palette stroke) ----------
# Emoji fonts render inconsistently across platforms; these are crisp at
# any size and always in the blue family.
ICONS = {
    "target": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.2"/>',
    "activity": '<polyline points="3 12 7 12 10 5 14 19 17 12 21 12"/>',
    "compass": '<circle cx="12" cy="12" r="9"/><polygon points="15.5 8.5 10.8 10.8 8.5 15.5 13.2 13.2 15.5 8.5"/>',
    "sliders": '<line x1="4" y1="7" x2="20" y2="7"/><circle cx="9" cy="7" r="2.2"/><line x1="4" y1="12" x2="20" y2="12"/><circle cx="15" cy="12" r="2.2"/><line x1="4" y1="17" x2="20" y2="17"/><circle cx="7" cy="17" r="2.2"/>',
    "scissors": '<circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><line x1="8" y1="8" x2="20" y2="18"/><line x1="8" y1="16" x2="20" y2="6"/>',
    "alert": '<path d="M12 3 L22 20 H2 Z"/><line x1="12" y1="10" x2="12" y2="14.5"/><circle cx="12" cy="17.2" r="0.4"/>',
    "check": '<circle cx="12" cy="12" r="9"/><polyline points="8.5 12.5 11 15 15.5 9.5"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15.5 13.5"/>',
    "trending": '<polyline points="3 17 9 11 13 15 21 7"/><polyline points="15 7 21 7 21 13"/>',
    "flask": '<path d="M9 3h6M10 3v6L4.5 19a2 2 0 0 0 1.8 3h11.4a2 2 0 0 0 1.8-3L14 9V3"/>',
    "grid": '<circle cx="6" cy="6" r="2.5"/><circle cx="17" cy="9" r="3.5"/><circle cx="11" cy="17" r="2"/>',
    "message": '<path d="M21 11.5a8.5 8.5 0 0 1-12.4 7.5L4 20l1-4.6A8.5 8.5 0 1 1 21 11.5z"/>',
    "zap": '<polygon points="13 2 4 14 11 14 10 22 20 9 12 9 13 2"/>',
    "rss": '<path d="M4 11a9 9 0 0 1 9 9"/><path d="M4 4a16 16 0 0 1 16 16"/><circle cx="5" cy="19" r="1"/>',
    "inbox": '<path d="M3 13h5l2 3h4l2-3h5"/><path d="M5 5h14l2 8v6H3v-6z"/>',
    "refresh": '<polyline points="21 12 21 17 16 17"/><polyline points="3 12 3 7 8 7"/><path d="M21 7a9 9 0 0 0-15-4L3 6"/><path d="M3 17a9 9 0 0 0 15 4l3-3"/>',
    "eye": '<circle cx="12" cy="12" r="3"/><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/>',
    "layers": '<polygon points="12 2 22 8.5 12 15 2 8.5 12 2"/><polyline points="2 15.5 12 22 22 15.5"/>',
    "book": '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V2H6.5A2.5 2.5 0 0 0 4 4.5z"/>',
    "upload": '<path d="M12 16V4"/><polyline points="7 9 12 4 17 9"/><path d="M4 20h16"/>',
    "paste": '<rect x="6" y="4" width="12" height="17" rx="2"/><path d="M9 4a3 3 0 0 1 6 0"/><line x1="9" y1="10" x2="15" y2="10"/><line x1="9" y1="14" x2="13" y2="14"/>',
    "sample": '<path d="M4 4h16v6H4z"/><path d="M4 14h16v6H4z"/><circle cx="8" cy="7" r="1"/><circle cx="8" cy="17" r="1"/>',
}


def icon(name, size=15, color="var(--blue-deep)"):
    """Inline SVG, vertically centred with text."""
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
            f'stroke="{color}" stroke-width="2" stroke-linecap="round" '
            f'stroke-linejoin="round" style="vertical-align:-2px">'
            f'{ICONS[name]}</svg>')


def section(title, name, size=16):
    """Section header: palette icon in a light-blue chip, bold title. Own
    div with controlled spacing — Streamlit's paragraph margins made the
    gap above headers smaller than the gap below them."""
    st.markdown(f'<div class="section-head">'
                f'<span class="icon-chip">{icon(name, size)}</span> '
                f"<b>{title}</b></div>", unsafe_allow_html=True)

# accent palette — light blue family
BLUE_DEEP = "#1971c2"     # primary actions / live series
BLUE = "#339af0"          # chosen highlight
BLUE_SOFT = "#74c0fc"     # chart points
BLUE_PALE = "#d0ebff"     # snapshot series / chips

# inbox buckets: which behaviour needs the human first
NEEDS_HUMAN = {Behaviour.ASK, Behaviour.REFUSE, Behaviour.IMPOSSIBLE,
               Behaviour.NO_DATA}

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
</style>
"""


def card(html, delay=0.0):
    """One card. delay staggers the entrance animation (seconds)."""
    style = f' style="animation-delay:{delay}s"' if delay else ""
    st.markdown(f'<div class="card"{style}>{html}</div>',
                unsafe_allow_html=True)


def queue_bar_html(queue_now, queue_added, scale):
    """Inline-SVG-free queue bar: current queue (soft blue) + this order's
    expected work (deep blue) stacked, widths as % of `scale` days. The
    fills grow from 0 via the qgrow keyframe, so bars animate in on every
    rerun — and re-rendered values visibly move when queues change."""
    now_pct = round(min(100.0, 100.0 * queue_now / scale), 1) if scale else 0
    add_pct = round(min(100.0 - now_pct, 100.0 * queue_added / scale), 1) \
        if scale else 0
    return (f'<div class="qbar-track">'
            f'<div class="qbar-fill qbar-now" style="width:{now_pct}%"></div>'
            f'<div class="qbar-fill qbar-add" style="width:{add_pct}%"></div>'
            f'</div>')


def _sync_anchor(link):
    """Invisible marker the scroll-sync script looks for."""
    st.markdown(f'<span class="sync-anchor" data-sync="{link}"></span>',
                unsafe_allow_html=True)


# ---------------- scroll sync: worklist card -> chat log ----------------

# Streamlit has no scroll events, so a tiny script is injected into the page
# (components.html runs same-origin, so it can reach window.parent). On
# every scroll of the main area it finds the worklist card at the middle of
# the screen, scrolls the sidebar chat log to the message with the same
# data-sync id and flashes it grey twice. Installed once per page (versioned, so a newer
# script replaces an older one); reruns don't stack it.
SCROLL_SYNC_JS = """
(function () {
  const w = window, doc = document, VERSION = 3;
  const old = w.__deskScrollSync;
  if (old && old.version === VERSION) return;
  if (old) doc.removeEventListener("scroll", old.onScroll, true);
  const css = doc.getElementById("desk-sync-css") || doc.createElement("style");
  css.id = "desk-sync-css";
  css.textContent = `
    @keyframes desk-blink { 0%,50%,100% { background: transparent; }
                            25%,75% { background: #e9ecef; } }
    .desk-blink { animation: desk-blink 1.2s ease-in-out 1; border-radius: 8px; }`;
  doc.head.appendChild(css);
  let active = null, timer = null;
  function scrollParent(el) {
    for (let p = el.parentElement; p; p = p.parentElement) {
      const oy = w.getComputedStyle(p).overflowY;
      if ((oy === "auto" || oy === "scroll") && p.scrollHeight > p.clientHeight) return p;
    }
    return null;
  }
  function sync() {
    const sidebar = doc.querySelector('[data-testid="stSidebar"]');
    if (!sidebar) return;
    const cards = [...doc.querySelectorAll(".sync-anchor")]
      .filter(a => !sidebar.contains(a));
    // the card at the middle of the screen wins (nearest one if the
    // middle falls in a gap between cards)
    const mid = w.innerHeight / 2;
    let link = null, best = Infinity;
    for (const a of cards) {
      const box = (a.closest('[data-testid="stExpander"]') || a).getBoundingClientRect();
      if (!box.height) continue;
      const dist = mid < box.top ? box.top - mid : mid > box.bottom ? mid - box.bottom : 0;
      if (dist < best) { best = dist; link = a.dataset.sync; }
    }
    if (!link || link === active) return;
    const anchor = sidebar.querySelector('.sync-anchor[data-sync="' + link + '"]');
    if (!anchor) return;
    active = link;
    const msg = anchor.closest('[data-testid="stChatMessage"]') || anchor.parentElement;
    const box = scrollParent(msg);
    if (box) box.scrollTo({ top: box.scrollTop + msg.getBoundingClientRect().top
                                 - box.getBoundingClientRect().top - 8,
                            behavior: "smooth" });
    msg.classList.remove("desk-blink");
    void msg.offsetWidth;            // restart the animation
    msg.classList.add("desk-blink");
  }
  function onScroll(e) {
    const sidebar = doc.querySelector('[data-testid="stSidebar"]');
    if (sidebar && e.target.nodeType === 1 && sidebar.contains(e.target)) return;
    w.clearTimeout(timer);
    timer = w.setTimeout(sync, 150);
  }
  doc.addEventListener("scroll", onScroll, true);
  w.__deskScrollSync = { version: VERSION, onScroll: onScroll };
})();
"""


def install_scroll_sync():
    """Copy the script into the app page itself (not this component's
    iframe), so it keeps running when Streamlit re-renders the iframe."""
    import json
    import streamlit.components.v1 as components
    components.html(
        "<script>const d = window.parent.document;"
        "const cur = window.parent.__deskScrollSync;"
        "if (!cur || cur.version !== 3) {"
        " const s = d.createElement('script');"
        f" s.textContent = {json.dumps(SCROLL_SYNC_JS)};"
        " d.head.appendChild(s); }</script>", height=0)
