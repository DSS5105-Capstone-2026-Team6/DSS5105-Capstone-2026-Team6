"""
theme.icons — the inline SVG icon set and the section header built on it.

Emoji fonts render inconsistently across platforms; these feather-style
icons are crisp at any size and always in the blue family.
"""

import streamlit as st

# ---------- inline SVG icon set (feather-style, palette stroke) ----------
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
