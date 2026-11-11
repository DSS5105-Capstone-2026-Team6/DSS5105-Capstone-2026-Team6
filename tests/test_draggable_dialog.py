"""Draggable dialog: the mover script installs without error."""

from streamlit.testing.v1 import AppTest


def _app():
    from app.components.draggable_dialog import make_dialog_movable
    make_dialog_movable()


def test_mover_injects_without_exception():
    at = AppTest.from_function(_app).run()
    assert not at.exception


def test_script_targets_dialog_and_guards_reinstall():
    from app.components import draggable_dialog as m
    # pins the contract the injected JS relies on; a rewrite must update both
    assert '[role="dialog"]' in m._JS
    assert "__deskDialogMover" in m._JS      # install-once guard
    assert "MutationObserver" in m._JS       # picks up re-rendered dialogs
