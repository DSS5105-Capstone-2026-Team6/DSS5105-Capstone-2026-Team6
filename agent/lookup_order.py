"""
lookup_order — resolve the order a chat message refers to.

Spec (roadmap Table 4): input is an order_id or customer/product/category
filters; output is the matching order rows. More than one match must come
back as "ambiguous" with every match (the routing code turns that into a
clarifying question); an unknown id returns "not_found" and never a nearest
match.

The OrderStore keeps the full orders.csv columns so later tools
(estimate_delivery, earliest_feasible) work from the same rows. With
stages=True it reads orders_stages.csv and exposes dispatch_stage — the
reading the chat inbox needs for the --stages extension.
"""

import csv
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"

ORDER_FIELDS = [
    "order_id", "customer", "product", "category", "pieces",
    "order_date", "due_date", "status", "current_stage",
]


class OrderStore:
    """Loads orders.csv (or orders_stages.csv when stages=True) once."""

    def __init__(self, data_dir=DATA_DIR, stages=False):
        self.stages = stages
        path = Path(data_dir) / ("orders_stages.csv" if stages else "orders.csv")
        with open(path, encoding="utf-8") as f:
            self.orders = list(csv.DictReader(f))
        self._fields = ORDER_FIELDS + (["dispatch_stage"] if stages else [])
        self._by_id = {r["order_id"]: r for r in self.orders}

    def by_id(self, order_id):
        return self._by_id.get(order_id)

    def row(self, record):
        """Project a raw CSV row to the public shape (all values strings)."""
        return {k: record[k] for k in self._fields}


def lookup_order(order_id=None, customer=None, product=None, category=None,
                 *, store=None):
    """Resolve an order. Returns {"status", "matches", "message"}.

    status: "found" (exactly one), "ambiguous" (several — ask, don't guess),
    "not_found" (none — never a nearest match).
    """
    store = store or OrderStore()

    if order_id:
        rec = store.by_id(order_id)
        if rec is None:
            return {"status": "not_found", "matches": [],
                    "message": f"No order with id {order_id} exists in orders.csv."}
        return {"status": "found", "matches": [store.row(rec)],
                "message": f"Found {order_id}."}

    if customer is None and product is None and category is None:
        return {"status": "not_found", "matches": [],
                "message": "No order_id or filters given; ask for the order id, "
                           "customer, product or category."}

    matches = store.orders
    if customer:
        matches = [r for r in matches if customer.lower() in r["customer"].lower()]
    if product:
        matches = [r for r in matches if product.lower() in r["product"].lower()]
    if category:
        matches = [r for r in matches if r["category"] == category.upper()]

    if not matches:
        return {"status": "not_found", "matches": [],
                "message": "No order matches those filters."}
    rows = [store.row(r) for r in matches]
    if len(rows) == 1:
        return {"status": "found", "matches": rows,
                "message": f"Found {rows[0]['order_id']}."}
    return {"status": "ambiguous", "matches": rows,
            "message": f"{len(rows)} orders match; ask which one is meant."}


LOOKUP_ORDER_SCHEMA = {
    "type": "function",
    "function": {
        "name": "lookup_order",
        "description": "Resolve the order a chat message refers to, by exact "
                       "order id or by customer/product/category filters. "
                       "Returns all matches; several matches means ask the "
                       "dispatcher which one is meant.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string",
                             "description": "Exact id, e.g. ORD-073"},
                "customer": {"type": "string",
                             "description": "Customer name (substring, case-insensitive)"},
                "product": {"type": "string",
                            "description": "Product name (substring, case-insensitive)"},
                "category": {"type": "string", "enum": ["TOPS", "ACCESSORIES"],
                             "description": "Product category"},
            },
            "required": [],
        },
    },
}


if __name__ == "__main__":
    import json
    import sys

    arg = " ".join(sys.argv[1:]) or "ORD-063"
    if arg.startswith("ORD-"):
        result = lookup_order(order_id=arg)
    else:
        result = lookup_order(customer=arg)
    print(json.dumps(result, indent=2, ensure_ascii=False))
