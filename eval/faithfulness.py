"""
faithfulness — verify that every number in the agent's explanation traces
back to a tool output or to the user's own message (roadmap Table 8 risk 1:
"The LLM states a number that no tool returned").

The checker never re-computes anything. It extracts every digit-bearing
token from the explanation, normalises it, and checks membership against an
evidence set built from:

  1. the tool log (every scalar in every tool result), and
  2. the user's raw message (numbers the user stated are legitimate to
     echo, e.g. "400 hoodies" or "due Apr 21").

Date forms are cross-normalised: "Apr 6", "6 Apr", "2026-04-06" and
"04-06" all canonicalise to the same month-day key, and a bare "2026" is
accepted whenever any tool returned a 2026 date. Percentages accept both
"3%" and the rate form "0.03". Money and thousands separators are stripped.

Known limitations (documented, not hidden): number words ("two shops") are
not extracted, and arithmetic on tool numbers ("about half of 600") is not
verified — the roadmap scores quoted numbers, not derived ones.

Usage:

    from eval.faithfulness import check_faithfulness
    report = check_faithfulness(explanation, tool_log, user_text)
    report.ok          # True when no violation was found
    report.violations  # ["600", ...] tokens with no traceable source

Run directly for a demo:  python eval/faithfulness.py
"""

import json
import re
from dataclasses import dataclass, field

# --- token extraction -------------------------------------------------------

_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
           "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}

# 2026-04-06 / 04-06 / 4/6 style dates
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_SLASH_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")
# April 6 / Apr 6 / 6 April / 6th of April handled by the two below
_MONTH_FIRST = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
    r"[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b", re.IGNORECASE)
_DAY_FIRST = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?"
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\b",
    re.IGNORECASE)
# ORD-073 / W6 / A-0001
_ID = re.compile(r"\b[A-Za-z]{1,6}-?\d+\b")
# 600 / 1,650 / $1,650.00 / 3% / 0.05
_NUM = re.compile(r"\$?\d[\d,]*(?:\.\d+)?%?")
# enumeration markers in replies: "1. **Which order**", "2) ..." — these
# are list positions, not claims about the world
_ORDINAL = re.compile(r"(?m)^\s*\d{1,2}[.)]\s+")


def _strip_ordinals(text):
    return _ORDINAL.sub(" ", text)


def _month_day(month, day):
    return f"{int(month)}-{int(day)}"


def extract_claims(text):
    """Every digit-bearing claim in `text`, as normalised strings.

    Dates canonicalise to "M-D"; ids keep their upper-cased form; plain
    numbers are comma/$ stripped (percent sign kept — matching tries both
    the raw and /100 form against the evidence)."""
    if not text:
        return []
    text = _strip_ordinals(text)
    claims = []
    seen_spans = []

    def claim(value, start, end):
        claims.append(value)
        seen_spans.append((start, end))

    for m in _ISO_DATE.finditer(text):
        claim(_month_day(m.group(2), m.group(3)), m.start(), m.end())
    for m in _SLASH_DATE.finditer(text):
        if any(s <= m.start() < e for s, e in seen_spans):
            continue                      # inside an ISO date already claimed
        claim(_month_day(m.group(1), m.group(2)), m.start(), m.end())
    for m in _MONTH_FIRST.finditer(text):
        claim(_month_day(_MONTHS[m.group(1).lower()], m.group(2)),
              m.start(), m.end())
    for m in _DAY_FIRST.finditer(text):
        claim(_month_day(_MONTHS[m.group(2).lower()], m.group(1)),
              m.start(), m.end())
    for m in _ID.finditer(text):
        if not any(s <= m.start() < e for s, e in seen_spans):
            claim(m.group(0).upper(), m.start(), m.end())
    for m in _NUM.finditer(text):
        if not any(s <= m.start() < e for s, e in seen_spans):
            claim(m.group(0), m.start(), m.end())
    return claims


def _normalise_num(token):
    """'$1,650.00%' -> '1650.00' plus percent flag."""
    pct = token.endswith("%")
    bare = token.lstrip("$").rstrip("%").replace(",", "")
    return bare, pct


# --- evidence ---------------------------------------------------------------

def _scalars(obj):
    """Every string/number leaf in nested tool results."""
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _scalars(v)
    elif isinstance(obj, (list, tuple)):
        yield str(len(obj))               # "6 of them" — the count of rows
        for v in obj:
            yield from _scalars(v)
    elif isinstance(obj, (str, int, float)) and not isinstance(obj, bool):
        yield obj


def build_evidence(tool_log, user_text=""):
    """Set of normalised claims the explanation is allowed to make.

    Tool results contribute their scalars; the user's message is a
    whitelist for echoing user-stated numbers."""
    evidence = set()
    texts = [str(s) for entry in (tool_log or [])
             for s in _scalars(entry.get("result", {}))]
    texts.append(str(user_text or ""))
    for t in texts:
        for claim in extract_claims(t):
            evidence.add(claim)
            bare, pct = _normalise_num(claim)
            if re.fullmatch(r"\d+(\.\d+)?", bare):
                evidence.add(bare)                    # 1,650 -> 1650
                value = float(bare)
                evidence.add(str(int(value)))         # 1650.0 -> 1650
                if pct:
                    evidence.add(f"{value / 100:g}")  # 3% -> 0.03
                elif 0 < value < 1:
                    # rate form from tools: 0.05 also licenses "5%"
                    evidence.add(f"{round(value * 100, 4):g}%")
                if "." in bare:
                    evidence.add(bare.rstrip("0").rstrip("."))
        # ISO dates also contribute their bare year (2026-04-06 -> 2026)
        for m in _ISO_DATE.finditer(t):
            evidence.add(m.group(1))
    return evidence


# --- report -----------------------------------------------------------------

@dataclass
class FaithfulnessReport:
    ok: bool
    violations: list = field(default_factory=list)
    claims: list = field(default_factory=list)


def check_faithfulness(explanation, tool_log, user_text=""):
    """Compare every number in `explanation` against the tool log plus the
    user's message. Returns a FaithfulnessReport; ok is True when every
    claim traces to evidence."""
    claims = extract_claims(explanation)
    evidence = build_evidence(tool_log, user_text)
    violations = []
    for claim in claims:
        bare, _ = _normalise_num(claim)
        candidates = {claim, bare}
        if "." in bare:
            candidates.add(bare.rstrip("0").rstrip("."))
        if not (candidates & evidence):
            violations.append(claim)
    return FaithfulnessReport(ok=not violations, violations=violations,
                              claims=claims)


if __name__ == "__main__":
    demo_log = [{"tool": "lookup_order",
                 "arguments": {"order_id": "ORD-073"},
                 "result": {"order_id": "ORD-073", "pieces": 400,
                            "due_date": "2026-04-20", "customer": "Loom & Leaf",
                            "category": "TOPS"}}]
    good = ("ORD-073 is 400 pieces (TOPS) due 2026-04-20 for Loom & Leaf."
            " Apr 20 is tight; Nimble Needle finishes 2026-04-06.")
    demo_log2 = demo_log + [{"tool": "rank_candidates",
                             "arguments": {"order_id": "ORD-073"},
                             "result": {"candidates": [
                                 {"workshop_id": "W6",
                                  "estimated_finish": "2026-04-06",
                                  "cost": 480.0, "defect_risk": 0.05}]}}]
    bad = "ORD-073 is about 500 pieces due Apr 22; Nimble Needle costs $400."
    for label, text, log in (("traceable", good, demo_log2),
                             ("hallucinated", bad, demo_log2)):
        r = check_faithfulness(text, log, "Send ORD-073 (400 hoodies)")
        print(f"[{label}] ok={r.ok} claims={r.claims}")
        if r.violations:
            print(f"  violations: {r.violations}")
    as_json = json.dumps({"tool": "x", "result": {"a": 1}}, default=str)
    assert json.loads(as_json)["result"]["a"] == 1
