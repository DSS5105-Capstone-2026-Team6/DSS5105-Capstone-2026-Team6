"""
components.draggable_dialog — make st.dialog movable and resizable.

Streamlit's native dialog is a static modal: three width presets, no drag,
no resize. The demo needs a preview window the presenter can move aside
and shrink, so a small script is injected into the page (same pattern as
theme/motion.py's scroll sync):

- resize: both + overflow on the dialog surface (native corner handle)
- drag by the dialog's top ~48px title strip: the dialog is re-anchored to
  explicit left/top on first drag and follows the cursor within the viewport

Selectors target Streamlit's internal dialog DOM ([role="dialog"]). A
Streamlit upgrade may rename them — the script then simply does nothing
(the dialog becomes static again); it never breaks the app. New dialog
nodes are picked up via a MutationObserver, so it survives Streamlit's
re-renders without stacking listeners.
"""

import streamlit as st

_JS = """
(function () {
  const w = window, doc = document;
  if (w.__deskDialogMover) return;          // install once per page
  w.__deskDialogMover = true;

  const css = doc.createElement("style");
  css.id = "desk-dialog-mover";
  css.textContent = `
    [role="dialog"] {
      resize: both;
      overflow: hidden;        /* inner container keeps its own scroll */
      min-width: 420px; min-height: 240px;
      max-width: 95vw; max-height: 90vh;
    }
  `;
  doc.head.appendChild(css);

  function bind(dlg) {
    if (dlg.__moverBound) return;
    dlg.__moverBound = true;
    dlg.addEventListener("mousedown", (e) => {
      const r = dlg.getBoundingClientRect();
      if (e.clientY - r.top > 48) return;    // title strip only
      // freeze the current position and drop Streamlit's centering
      dlg.style.position = "fixed";
      dlg.style.left = r.left + "px";
      dlg.style.top = r.top + "px";
      dlg.style.margin = "0";
      dlg.style.transform = "none";
      const dx = e.clientX - r.left, dy = e.clientY - r.top;
      e.preventDefault();
      function move(ev) {
        dlg.style.left = Math.max(0, Math.min(w.innerWidth - 80,
                                              ev.clientX - dx)) + "px";
        dlg.style.top = Math.max(0, Math.min(w.innerHeight - 48,
                                             ev.clientY - dy)) + "px";
      }
      function up() {
        doc.removeEventListener("mousemove", move, true);
        doc.removeEventListener("mouseup", up, true);
      }
      doc.addEventListener("mousemove", move, true);
      doc.addEventListener("mouseup", up, true);
    }, true);
  }

  function scan() { doc.querySelectorAll('[role="dialog"]').forEach(bind); }
  scan();
  new MutationObserver(scan).observe(doc.body, { childList: true, subtree: true });
})();
"""


def make_dialog_movable():
    """Inject the mover script into the app page itself (not this
    component's iframe), so it keeps working across Streamlit reruns."""
    import json
    import streamlit.components.v1 as components
    components.html(
        "<script>const d = window.parent.document;"
        "if (!window.parent.__deskDialogMover) {"
        " const s = d.createElement('script');"
        f" s.textContent = {json.dumps(_JS)};"
        " d.head.appendChild(s); }</script>", height=0)
