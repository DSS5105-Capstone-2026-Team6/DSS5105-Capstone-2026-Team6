"""
theme.tokens — the design constants every surface shares: the light-blue
palette and the behaviour badge table.

Pure data: imports nothing from the app layer, so any module can read these
without import-order worries.
"""

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

# accent palette — light blue family
BLUE_DEEP = "#1971c2"     # primary actions / live series
BLUE = "#339af0"          # chosen highlight
BLUE_SOFT = "#74c0fc"     # chart points
BLUE_PALE = "#d0ebff"     # snapshot series / chips

# inbox buckets: which behaviour needs the human first
NEEDS_HUMAN = {Behaviour.ASK, Behaviour.REFUSE, Behaviour.IMPOSSIBLE,
               Behaviour.NO_DATA}
