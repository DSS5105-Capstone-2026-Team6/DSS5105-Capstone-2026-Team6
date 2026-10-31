"""Unit tests for the presentational helpers in app/ui_shared.py — the
animated queue bar rendered inside order cards."""

from app.ui_shared import queue_bar_html


def test_bar_widths_proportional_to_scale():
    html = queue_bar_html(5.0, 5.0, scale=20.0)
    assert "width:25.0%" in html      # 5/20 each
    assert html.count("qbar-fill") == 2


def test_added_load_capped_when_it_overflows():
    """Failure case: queue + order beyond the scale must not overflow the
    track — the second fill is capped, not the layout broken."""
    html = queue_bar_html(18.0, 10.0, scale=20.0)
    assert "width:90.0%" in html                       # 18/20
    assert "width:10.0%" in html                       # capped to the rest
    assert "width:100.0%" not in html.replace("90.0%", "").replace("10.0%", "")


def test_zero_scale_does_not_divide_by_zero():
    assert "width:0%" in queue_bar_html(0.0, 0.0, scale=0.0)
