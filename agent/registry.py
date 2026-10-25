"""
registry — the tool layer the LLM calls through.

TOOL_REGISTRY maps each of the eight core tools (roadmap Table 4) to its
JSON schema (sent to the model) and its Python function (executed locally,
no LLM). dispatch_tool() is the single entry point: it resolves the shared
stores from the desk context when one is given, so tools and simulator
always read the same data.
"""

try:
    from .lookup_order import OrderStore, lookup_order, LOOKUP_ORDER_SCHEMA
    from .check_eligibility import (WorkshopStore, check_eligibility,
                                    CHECK_ELIGIBILITY_SCHEMA)
    from .get_queue import get_queue, GET_QUEUE_SCHEMA
    from .estimate_delivery import (estimate_delivery,
                                    ESTIMATE_DELIVERY_SCHEMA)
    from .rank_candidates import (rank_candidates,
                                  RANK_CANDIDATES_SCHEMA)
    from .probe_overload import probe_overload, PROBE_OVERLOAD_SCHEMA
    from .earliest_feasible import (earliest_feasible,
                                    EARLIEST_FEASIBLE_SCHEMA)
    from .commit_allocation import (commit_allocation,
                                    COMMIT_ALLOCATION_SCHEMA)
except ImportError:  # run directly as a script: python agent/registry.py
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from agent.lookup_order import OrderStore, lookup_order, LOOKUP_ORDER_SCHEMA
    from agent.check_eligibility import (WorkshopStore, check_eligibility,
                                         CHECK_ELIGIBILITY_SCHEMA)
    from agent.get_queue import get_queue, GET_QUEUE_SCHEMA
    from agent.estimate_delivery import (estimate_delivery,
                                         ESTIMATE_DELIVERY_SCHEMA)
    from agent.rank_candidates import (rank_candidates,
                                       RANK_CANDIDATES_SCHEMA)
    from agent.probe_overload import probe_overload, PROBE_OVERLOAD_SCHEMA
    from agent.earliest_feasible import (earliest_feasible,
                                         EARLIEST_FEASIBLE_SCHEMA)
    from agent.commit_allocation import (commit_allocation,
                                         COMMIT_ALLOCATION_SCHEMA)


TOOL_REGISTRY = {
    "lookup_order": {"schema": LOOKUP_ORDER_SCHEMA, "func": lookup_order},
    "check_eligibility": {"schema": CHECK_ELIGIBILITY_SCHEMA,
                          "func": check_eligibility},
    "get_queue": {"schema": GET_QUEUE_SCHEMA, "func": get_queue},
    "estimate_delivery": {"schema": ESTIMATE_DELIVERY_SCHEMA,
                          "func": estimate_delivery},
    "rank_candidates": {"schema": RANK_CANDIDATES_SCHEMA,
                        "func": rank_candidates},
    "probe_overload": {"schema": PROBE_OVERLOAD_SCHEMA, "func": probe_overload},
    "earliest_feasible": {"schema": EARLIEST_FEASIBLE_SCHEMA,
                          "func": earliest_feasible},
    "commit_allocation": {"schema": COMMIT_ALLOCATION_SCHEMA,
                          "func": commit_allocation},
}

# which store each kwarg receives ("orders" = OrderStore, "workshops" =
# WorkshopStore); lookup_order's kwarg is named "store" but holds orders
_STORE_KWARGS = {
    "lookup_order": {"store": "orders"},
    "check_eligibility": {"store": "workshops"},
    "get_queue": {"store": "workshops"},
    "estimate_delivery": {"orders": "orders", "store": "workshops"},
    "rank_candidates": {"orders": "orders", "store": "workshops"},
    "earliest_feasible": {"orders": "orders", "store": "workshops"},
}
_FACTORIES = {"orders": OrderStore, "workshops": WorkshopStore}


def tool_schemas():
    """The schemas to pass as `tools=` to the chat completion."""
    return [entry["schema"] for entry in TOOL_REGISTRY.values()]


def dispatch_tool(name, arguments, *, desk=None):
    """Execute one tool call from the model. Returns the tool's result dict
    (or an error dict the model can read and relay). With a desk, tools read
    its shared stores and commit_allocation can write state; without one,
    fresh stores are built and the committer refuses (nothing to commit to)."""
    entry = TOOL_REGISTRY.get(name)
    if entry is None:
        return {"error": f"unknown tool {name!r}"}
    kwargs = dict(arguments or {})
    if name == "commit_allocation":
        kwargs["orders"] = desk.orders if desk else None
        kwargs["desk"] = desk
    else:
        for param, kind in _STORE_KWARGS.get(name, {}).items():
            if desk is not None:
                kwargs[param] = getattr(desk, kind)
            else:
                kwargs[param] = _FACTORIES[kind]()
    try:
        return entry["func"](**kwargs)
    except (TypeError, ValueError) as exc:
        return {"error": f"bad arguments for {name}: {exc}"}


if __name__ == "__main__":
    print(f"{len(TOOL_REGISTRY)} tools registered (all implemented):")
    for name in TOOL_REGISTRY:
        print(f"  {name}")
    print("\nsample dispatch:")
    print(dispatch_tool("lookup_order", {"order_id": "ORD-063"}))
