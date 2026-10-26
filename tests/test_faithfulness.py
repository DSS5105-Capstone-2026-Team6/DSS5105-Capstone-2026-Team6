"""Faithfulness checker: numbers in the explanation must trace to the tool
log or the user's message — plus one deliberate violation per happy path."""

import pytest

from eval.faithfulness import (build_evidence, check_faithfulness,
                               extract_claims)

LOG = [{"tool": "lookup_order",
        "arguments": {"order_id": "ORD-073"},
        "result": {"order_id": "ORD-073", "pieces": 400, "category": "TOPS",
                   "due_date": "2026-04-20", "customer": "Loom & Leaf"}},
       {"tool": "rank_candidates",
        "arguments": {"order_id": "ORD-073"},
        "result": {"candidates": [
            {"workshop_id": "W6", "name": "Nimble Needle",
             "estimated_finish": "2026-04-06", "days_late": 0,
             "cost": 480.0, "defect_risk": 0.05, "slack_days": 14}]}}]

USER = "Send ORD-073 (400 hoodies) to FreshStart, due Apr 20."


# --- extraction -------------------------------------------------------------

def test_extract_iso_date_claim():
    assert extract_claims("due 2026-04-20") == ["4-20"]


def test_extract_month_first_and_day_first():
    assert extract_claims("Apr 6") == ["4-6"]
    assert extract_claims("6 April") == ["4-6"]


def test_extract_ids_and_numbers():
    claims = extract_claims("ORD-073 is 1,650 pieces at $2.50, 3% defect")
    assert "ORD-073" in claims and "1,650" in claims
    assert "$2.50" in claims and "3%" in claims


# --- happy paths ------------------------------------------------------------

def test_tool_number_is_faithful():
    r = check_faithfulness("ORD-073 is 400 pieces.", LOG, "")
    assert r.ok, r.violations


def test_tool_date_multiple_forms():
    for text in ("Nimble Needle finishes 2026-04-06.",
                 "Nimble Needle finishes Apr 6.",
                 "Nimble Needle finishes April 6th.",
                 "Nimble Needle finishes 6 Apr."):
        r = check_faithfulness(text, LOG, "")
        assert r.ok, (text, r.violations)


def test_user_stated_number_is_whitelisted():
    # FreshStart appears only in the user's message, never in tool results.
    r = check_faithfulness("You asked for FreshStart, but ...", LOG, USER)
    assert r.ok, r.violations


def test_money_and_percent_forms():
    r = check_faithfulness("Nimble Needle costs $480, defect risk 5%.",
                           LOG, "")
    assert r.ok, r.violations
    r2 = check_faithfulness("Nimble Needle costs 480.00, defect risk 0.05.",
                            LOG, "")
    assert r2.ok, r2.violations


# --- failure cases (each must be caught) -------------------------------------

def test_hallucinated_piece_count_flagged():
    r = check_faithfulness("ORD-073 is 500 pieces.", LOG, USER)
    assert not r.ok and "500" in r.violations


def test_hallucinated_date_flagged():
    r = check_faithfulness("Nimble Needle finishes Apr 9.", LOG, "")
    assert not r.ok and "4-9" in r.violations


def test_hallucinated_cost_flagged():
    # 320 is in no tool result and in no user message.
    r = check_faithfulness("Nimble Needle costs $320.", LOG, USER)
    assert not r.ok and "$320" in r.violations


def test_report_lists_all_violations():
    r = check_faithfulness("500 pieces due Apr 22 at $320.", LOG, USER)
    assert set(r.violations) == {"500", "4-22", "$320"}


def test_list_ordinals_are_not_claims():
    # "1. Which order? 2. Batch size" — positions, not facts.
    r = check_faithfulness("I need:\n1. **Which order**\n2. **Batch size**\n"
                           "3. **Due date**", LOG, "")
    assert r.ok, r.violations


# --- evidence ----------------------------------------------------------------

def test_evidence_includes_user_numbers():
    ev = build_evidence([], "due Mar 29, 600 pieces")
    assert "3-29" in ev and "600" in ev


def test_evidence_percent_matches_rate():
    ev = build_evidence([{"tool": "t", "arguments": {},
                          "result": {"defect_risk": 0.03}}], "")
    assert "0.03" in ev


def test_evidence_includes_list_length():
    # "3 of 8 eligible" — 8 is the row count the tool returned.
    ev = build_evidence([{"tool": "t", "arguments": {},
                          "result": {"workshops": [{"w": i} for i in range(8)]}}],
                        "")
    assert "8" in ev
