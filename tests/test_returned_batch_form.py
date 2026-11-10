"""Record a returned batch: Pieces is remembered per workshop."""

from streamlit.testing.v1 import AppTest


def _app():
    from types import SimpleNamespace
    from app.sidebar import batch_recorder as sb
    import desk.tools as tools
    ws = {wid: SimpleNamespace(workshop_id=wid, name=n, capacity=100, lead_days=2)
          for wid, n in [("W1", "QuickStitch"), ("W2", "SteadyHands")]}
    perf = SimpleNamespace(learned=lambda wid, profile=None: None)
    desk = SimpleNamespace(workshops=SimpleNamespace(workshops=ws), performance=perf)
    tools.update_workshop_performance = lambda *a, **k: {"delay_days": 0, "note": "ok"}
    sb.render_performance_sidebar(desk)


def test_pieces_remembered_per_workshop():
    at = AppTest.from_function(_app).run()
    assert not at.exception
    at.number_input(key="rb_pieces_W1").set_value(600).run()
    at.selectbox(key="rb_workshop").set_value(at.selectbox(key="rb_workshop").options[1]).run()
    assert at.number_input(key="rb_pieces_W2").value == 400
    at.number_input(key="rb_pieces_W2").set_value(250).run()
    at.selectbox(key="rb_workshop").set_value(at.selectbox(key="rb_workshop").options[0]).run()
    assert at.number_input(key="rb_pieces_W1").value == 600
    at.button(key="rb_record").click().run()
    assert not at.exception
    assert at.number_input(key="rb_pieces_W1").value == 600
