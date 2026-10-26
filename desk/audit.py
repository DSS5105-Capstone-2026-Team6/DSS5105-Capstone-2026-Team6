"""
audit — the append-only JSONL audit log.

One readable line per committed allocation (roadmap §1.3: "easy to inspect,
diff and replay"). Append-only by construction: AuditLog has no update or
delete method, and the file is opened in "a" mode only.
"""

import json
from pathlib import Path

try:
    from .contracts import AllocationRecord, allocation_from_dict, to_dict
    from .config import DEFAULT_AUDIT_PATH
except ImportError:  # run directly as a script
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from desk.contracts import AllocationRecord, allocation_from_dict, to_dict
    from desk.config import DEFAULT_AUDIT_PATH

DEFAULT_PATH = DEFAULT_AUDIT_PATH


class AuditLog:
    def __init__(self, path=DEFAULT_PATH):
        self.path = Path(path)

    def append(self, record: AllocationRecord):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(to_dict(record), ensure_ascii=False) + "\n")

    def load_all(self):
        if not self.path.exists():
            return []
        with open(self.path, encoding="utf-8") as f:
            return [allocation_from_dict(json.loads(line))
                    for line in f if line.strip()]


if __name__ == "__main__":
    import datetime
    log = AuditLog()
    log.append(AllocationRecord(
        record_id="A-0000", decision_id="SMOKE", order_id="ORD-000",
        workshop_id="W6", pieces=1, committed_by="smoke-test",
        committed_at=datetime.datetime.now().isoformat(timespec="seconds")))
    print(f"appended; {len(log.load_all())} record(s) in {log.path}")
