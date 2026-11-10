"""
theme.motion — the scroll behaviours: worklist card -> chat log sync, and
scroll-to-next-order after a commit.

Streamlit has no scroll events, so tiny scripts are injected into the page
(components.html runs same-origin, so it can reach window.parent).
"""

import streamlit as st


def _sync_anchor(link):
    """Invisible marker the scroll-sync script looks for."""
    st.markdown(f'<span class="sync-anchor" data-sync="{link}"></span>',
                unsafe_allow_html=True)


# ---------------- scroll sync: worklist card -> chat log ----------------

# On every scroll of the main area the script finds the worklist card at
# the middle of the screen, scrolls the sidebar chat log to the message
# with the same data-sync id and flashes it grey twice. Installed once per
# page (versioned, so a newer script replaces an older one); reruns don't
# stack it.
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


def scroll_to_anchor(link):
    """Scroll the main area so the worklist expander holding the
    .sync-anchor `link` sits at the top of the screen (just under the
    Streamlit header).

    The committed card collapses WHILE we scroll, which moves the target.
    A fixed scrollTo(smooth) therefore overshot and had to jump back. This
    eases toward the target's LIVE position every animation frame, so it
    follows the layout shift in one continuous motion and settles without
    a correction. A counter makes each call a new component (runs every
    time); the user's own wheel/touch input cancels the animation."""
    import json
    import streamlit.components.v1 as components
    n = st.session_state["_scroll_n"] = st.session_state.get("_scroll_n", 0) + 1
    components.html(f"""<script>/* {n} */
    (function () {{
      const w = window.parent, doc = w.document, link = {json.dumps(link)};
      if (w.__deskScrollAnim) w.__deskScrollAnim.stop();   // one at a time
      let tries = 0, stopped = false, still = 0, start = 0;
      const stop = () => {{ stopped = true;
        ["wheel", "touchstart", "keydown"].forEach(e => doc.removeEventListener(e, stop, true)); }};
      w.__deskScrollAnim = {{ stop }};
      ["wheel", "touchstart", "keydown"].forEach(e => doc.addEventListener(e, stop, true));
      function find() {{
        const sidebar = doc.querySelector('[data-testid="stSidebar"]');
        const a = [...doc.querySelectorAll('.sync-anchor[data-sync="' + link + '"]')]
                    .find(x => !(sidebar && sidebar.contains(x)));
        return a && (a.closest('[data-testid="stExpander"]') || a);
      }}
      function scroller(el) {{
        for (let b = el.parentElement; b; b = b.parentElement)
          if (b.scrollHeight > b.clientHeight && /auto|scroll/.test(w.getComputedStyle(b).overflowY)) return b;
        return doc.scrollingElement;
      }}
      function begin() {{
        const target = find();
        if (!target) {{ if (tries++ < 30) w.setTimeout(begin, 80); else stop(); return; }}
        const box = scroller(target);
        const header = doc.querySelector('[data-testid="stHeader"]');
        const offset = (header ? header.getBoundingClientRect().height : 0) + 8;
        start = w.performance.now();
        function frame(now) {{
          if (stopped) return;
          const want = box.scrollTop + target.getBoundingClientRect().top
                       - box.getBoundingClientRect().top - offset;
          const max = box.scrollHeight - box.clientHeight;
          const goal = Math.max(0, Math.min(max, want));
          const diff = goal - box.scrollTop;
          if (Math.abs(diff) < 1) {{ box.scrollTop = goal; still++; }}
          else {{ box.scrollTop += diff * 0.16; still = 0; }}   // ease-out, tracks moves
          // done once settled for ~10 frames, or after 2.5 s at the latest
          if (still > 10 || now - start > 2500) {{ stop(); return; }}
          w.requestAnimationFrame(frame);
        }}
        w.requestAnimationFrame(frame);
      }}
      w.setTimeout(begin, 60);
    }})();
    </script>""", height=0)
