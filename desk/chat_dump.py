"""
chat_dump — split a pasted group-chat dump into single messages.

Three line shapes are recognised, in priority order:
1. numbered envelope   R01 [09:18] Priya: ...   (also H01 — the held-out
   inbox uses the same format; any single capital letter + digits counts)
2. bare chat line      [09:18] Priya: ...  or  Priya: ...   (no id at all —
   the dispatcher pastes raw chat too, and those lines must dispatch like
   numbered ones)
3. continuation        anything else joins the previous message ("make
   Apr 29" wrapping onto the line above)

Comments (#) and blank lines are skipped. eval/run_eval.py parses the
numbered inbox files with ENVELOPE; app/ and adapter/ split pasted dumps
with split_chat_dump().
"""

import re

# R01 [09:18] Priya: <text>   /   H01 [09:18] Priya: <text>
ENVELOPE = re.compile(r"^([A-Z]?\d{1,3})\s+\[(\d{2}:\d{2})\]\s+([^:]{1,40}):\s+(.*)$")

# [09:18] Priya: <text>   /   Priya: <text>
BARE_LINE = re.compile(r"^(?:\[\d{2}:\d{2}\]\s+)?[^:]{1,40}:\s+.+$")


def split_chat_dump(text):
    """Pasted dump -> list of single message strings. A line matching
    ENVELOPE or BARE_LINE starts a new message; other lines continue the
    previous one. A dump that is only comments/blank lines yields nothing."""
    msgs, current = [], None
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ENVELOPE.match(stripped) or BARE_LINE.match(stripped):
            if current:
                msgs.append(current)
            current = stripped
        elif current is None:
            current = stripped
        else:
            current += " " + stripped
    if current:
        msgs.append(current)
    return msgs
