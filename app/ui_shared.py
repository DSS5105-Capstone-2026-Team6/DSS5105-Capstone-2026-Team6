"""
ui_shared — constants and leaf helpers shared by every UI module.

Imports only streamlit + desk.contracts (never app.streamlit_app), so every
other app module can import this one safely.
"""

import streamlit as st

from desk.contracts import Behaviour

# behaviour badge chips: text + tint. Semantics come first (green/red/
# orange/blue); everything else in the UI stays in the light-blue family.
BADGE = {
    Behaviour.ALLOCATE: ("🟢 ALLOCATE", "#d3f9d8"),
    Behaviour.REFUSE: ("🔴 REFUSE", "#ffe3e3"),
    Behaviour.IMPOSSIBLE: ("🟠 IMPOSSIBLE", "#ffe8cc"),
    Behaviour.ASK: ("🔵 ASK", "#d0ebff"),
    Behaviour.ANSWER: ("⚪ ANSWER", "#e9ecef"),
    Behaviour.NO_DATA: ("⚪ NO DATA", "#e9ecef"),
}

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
.block-container {
    max-width: 1200px;     /* ~2/3 wider than Streamlit's centered 730px */
    margin: auto;
}
.card {
    border: 1px solid #dee2e6; border-radius: 12px;
    padding: 12px 14px; margin: 8px 0; background: #fff;
    animation: fadeUp .35s ease both;   /* entrance: slide + fade */
}
.card.chosen { border: 2px solid #339af0; background: #f1f8fe; }
.muted { color: #868e96; font-size: 0.85em; }
.field { margin: 2px 0; }
.field b { display: inline-block; min-width: 7.5em; }
h1 { font-size: 1.4rem !important; }

@keyframes fadeUp {
    from { opacity: 0; transform: translateY(8px); }
    to   { opacity: 1; transform: translateY(0); }
}

/* per-candidate live-queue bars (rendered inside order cards) */
.qbar-track {
    display: flex; height: 10px; border-radius: 6px;
    background: #e9ecef; overflow: hidden; margin: 6px 0 4px;
}
.qbar-fill { height: 100%; animation: qgrow .9s cubic-bezier(.2,.8,.2,1) both; }
.qbar-now  { background: #74c0fc; }   /* queue the shop already holds */
.qbar-add  { background: #1971c2; }   /* this order stacked on top */
@keyframes qgrow { from { width: 0; } }
.qbar-legend { color: #868e96; font-size: 0.8em; }
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
