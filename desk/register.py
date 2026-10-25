"""
register — the shared data stores the tools read from.

OrderStore keeps the full orders.csv columns so later tools
(estimate_delivery, earliest_feasible) work from the same rows. With
stages=True it reads orders_stages.csv and exposes dispatch_stage — the
reading the chat inbox needs for the --stages extension.

WorkshopStore loads workshops.csv (or workshops_stages.csv) via the
simulator's own loader so the eligibility rules can never drift apart.
"""

import csv
from pathlib import Path

try:
    from desk.config import DATA_DIR
    from harness.simulate import load_workshops
except ImportError:  # run directly as a script: python desk/register.py
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from desk.config import DATA_DIR
    from harness.simulate import load_workshops

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


class WorkshopStore:
    """Loads workshops.csv (or workshops_stages.csv when stages=True) once,
    via the simulator's own loader so the rules can never drift apart."""

    def __init__(self, stages=False):
        self.stages = stages
        self.workshops = load_workshops(stages)
        self._by_name = {w.name.lower(): w.workshop_id for w in self.workshops.values()}

    def resolve(self, name_or_id):
        """'W1' or 'quickstitch' -> 'W1'; None if unknown."""
        if name_or_id in self.workshops:
            return name_or_id
        return self._by_name.get(name_or_id.lower())


if __name__ == "__main__":
    import json
    orders = OrderStore()
    print(json.dumps(orders.row(orders.by_id("ORD-063")), indent=2,
                     ensure_ascii=False))
    workshops = WorkshopStore()
    print(json.dumps(sorted(workshops.workshops), indent=2))
    print("resolve 'quickstitch' ->", workshops.resolve("quickstitch"))
