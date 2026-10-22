"""
registry — the tool layer the LLM calls through.

TOOL_REGISTRY maps each tool name to its JSON schema (sent to the model) and
its Python function (executed locally, no LLM). dispatch_tool() is the single
entry point used by the tool-calling loop in llm.py.

lookup_order is implemented; the other seven core tools from the roadmap
(Table 4) are registered as placeholders so the schema surface is complete —
fill each one in and the LLM side needs no changes.
"""

try:
    from .lookup_order import OrderStore, lookup_order, LOOKUP_ORDER_SCHEMA
except ImportError:  # run directly as a script: python agent/registry.py
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from agent.lookup_order import OrderStore, lookup_order, LOOKUP_ORDER_SCHEMA


def _placeholder(name):
    def run(**_kwargs):
        raise NotImplementedError(f"tool {name!r} is registered but not implemented yet")
    return run


def _placeholder_schema(name, description):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }


_PLACEHOLDERS = {
    "check_eligibility": "For each workshop: eligible yes/no with the reason "
                         "(suspended, cannot make, over cap, excluded).",
    "get_queue": "Days of work each workshop currently holds.",
    "estimate_delivery": "Queue + processing + transport = finish date, slack "
                         "against the due date, cost and defect risk.",
    "rank_candidates": "Eligible workshops sorted by the objective score, "
                       "with all estimates. The allocator.",
    "probe_overload": "What happens to a workshop's queue if it takes "
                      "additional pieces. Read-only.",
    "earliest_feasible": "Earliest achievable date for an order, single batch "
                         "or split.",
    "commit_allocation": "Write the audit record after human confirmation. "
                         "Re-checks eligibility first.",
}

TOOL_REGISTRY = {
    "lookup_order": {"schema": LOOKUP_ORDER_SCHEMA, "func": lookup_order},
    **{name: {"schema": _placeholder_schema(name, desc), "func": _placeholder(name)}
       for name, desc in _PLACEHOLDERS.items()},
}


def tool_schemas():
    """The schemas to pass as `tools=` to the chat completion."""
    return [entry["schema"] for entry in TOOL_REGISTRY.values()]


def dispatch_tool(name, arguments, *, store=None):
    """Execute one tool call from the model. Returns the tool's result dict
    (or an error dict the model can read and relay)."""
    entry = TOOL_REGISTRY.get(name)
    if entry is None:
        return {"error": f"unknown tool {name!r}"}
    kwargs = dict(arguments or {})
    if name == "lookup_order":
        kwargs["store"] = store or OrderStore()
    try:
        return entry["func"](**kwargs)
    except NotImplementedError as exc:
        return {"error": str(exc)}
    except (TypeError, ValueError) as exc:
        return {"error": f"bad arguments for {name}: {exc}"}


if __name__ == "__main__":
    print(f"{len(TOOL_REGISTRY)} tools registered:")
    for name, entry in TOOL_REGISTRY.items():
        implemented = entry["func"].__name__ != "run"
        print(f"  {name:<24} {'implemented' if implemented else 'placeholder'}")
    print("\nsample dispatch:")
    print(dispatch_tool("lookup_order", {"order_id": "ORD-063"}))
