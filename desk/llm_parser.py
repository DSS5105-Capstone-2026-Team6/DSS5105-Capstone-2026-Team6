"""
llm_parser — semantic message parsing by the LLM, as an explicit contrast
to the rule-based splitter (desk/chat_dump.py).

chat_dump answers "where does one message end and the next begin" with
regexes; this module answers "what does this message MEAN" with the model:
order references, quantities, dates, intent and constraints, returned as
structured JSON. The rule layer still owns splitting and behaviour routing;
the LLM parser is an analysis surface (sidebar panel, future intake for
freeform channels). No tool calls, temperature 0, values only from the text.
"""

import json
import re

PARSE_SYSTEM = """You extract dispatch information from knitwear factory chat messages.
Reply with ONLY a JSON object (no prose, no markdown fences):
{
  "orders": [
    {"order_id": str|null, "customer": str|null, "product": str|null,
     "category": "TOPS"|"ACCESSORIES"|null, "pieces": int|null,
     "due_date": "YYYY-MM-DD"|null}
  ],
  "intent": "allocate|query|constraint|risk|other",
  "constraints": [{"type": "exclude|objective|date_change|other",
                   "detail": str, "imposed_by": str|null}]
}
Rules:
- use ONLY values stated in the message; unknown -> null
- order ids look like ORD-000; keep them verbatim
- dates must be normalised to YYYY-MM-DD (the year is 2026 when omitted)
- if nothing order-like is present, return an empty "orders" list"""


def parse_message(text, agent):
    """One freeform message -> structured dict. Uses the desk's agent client
    (provider/model the user picked). Returns {"error": ...} on bad output
    instead of raising."""
    # Go through agent._completion, like every other LLM call in the desk:
    # it adds reasoning_effort="none" and max_completion_tokens for OpenAI
    # (GPT reasoning models reject temperature=0 without them -> 400) and
    # counts the call against the API budget.
    try:
        resp = agent._completion(
            model=agent.model,
            messages=[{"role": "system", "content": PARSE_SYSTEM},
                      {"role": "user", "content": text}],
            temperature=0)
    except Exception as exc:   # budget limit, 400, network: show, don't crash
        return {"error": f"LLM call failed: {exc}"}
    raw = resp.choices[0].message.content or ""
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        return {"error": "no JSON in model output", "raw": raw}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        return {"error": f"bad JSON: {exc}", "raw": raw}


if __name__ == "__main__":
    # smoke test: uv run python desk/llm_parser.py "Ravi: ORD-063 — 100
    # cardigans, make Apr 29, keep it away from BudgetWorks"
    import sys
    from desk.agent import DispatchAgent
    text = " ".join(sys.argv[1:]) or "ORD-063 — 100 cardigans, make Apr 29."
    print(json.dumps(parse_message(text, DispatchAgent()),
                     indent=2, ensure_ascii=False))
