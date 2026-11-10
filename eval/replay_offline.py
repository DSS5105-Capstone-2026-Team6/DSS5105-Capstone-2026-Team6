"""
replay_offline — re-evaluate a recorded run with the CURRENT desk code,
without calling any LLM.

Each record in a run file (results/*_run*.jsonl) holds the LLM's reply and
the tool log it produced. This script feeds exactly those back through the
current DispatchDesk.handle_message (router, ranking attach, recommendation
consistency, _fill_impossible, split attach) and scores the result with
eval/score_run.py. Only the LLM step is held fixed, so the score difference
against the original run isolates the effect of code changes since then.

It cannot show changes that work through the LLM itself (prompt edits, new
tool messages the model would read); those need a live run_eval.py.

Usage:

    python eval/replay_offline.py                       # dev + held-out
    python eval/replay_offline.py --out-dir results     # also keep the files
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from desk.config import DATA_DIR, RESULTS_DIR
from desk.contracts import to_dict
from desk.desk import DispatchDesk
from desk.register import OrderStore, WorkshopStore
from eval.score_run import score_run

SETS = {
    "dev": (RESULTS_DIR / "inbox_run_v22b.jsonl", DATA_DIR / "labels_inbox.json"),
    "heldout": (RESULTS_DIR / "heldout_run.jsonl", DATA_DIR / "labels_heldout.json"),
}


class ReplayAgent:
    """Stands in for DispatchAgent: returns the recorded reply and tool log."""

    def __init__(self):
        self.workshops = WorkshopStore()
        self.store = OrderStore()
        self.tool_log, self.history = [], []
        self.desk = self.budget = self.record = None

    def chat(self, text, verbose=False):
        self.tool_log = self.record["tool_log"]
        return self.record["explanation"]


def replay(run_path, out_path):
    records = [json.loads(line) for line in open(run_path, encoding="utf-8")][1:]
    agent = ReplayAgent()
    with tempfile.TemporaryDirectory() as tmp:
        desk = DispatchDesk(agent=agent, as_of="2026-04-01", storage_dir=tmp)
        rows = []
        for record in records:
            agent.record = record
            decision = desk.handle_message(record["raw"], request_id=record["request_id"])
            rows.append(dict(to_dict(decision), raw=record["raw"],
                             speaker=record.get("speaker"),
                             latency_s=record.get("latency_s"),
                             request_id=record["request_id"]))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"meta": {"replay_of": str(run_path)}}) + "\n")
        for row in rows:
            f.write(json.dumps(row, default=str) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default=None,
                        help="keep replay runs and scores here (default: temp dir)")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(args.out_dir or tmp)
        for name, (run_path, labels) in SETS.items():
            out = out_dir / f"replay_{name}.jsonl"
            replay(run_path, out)
            rows, s = score_run(labels_path=labels, results_path=out)
            if args.out_dir:
                (out_dir / f"replay_{name}_scores.json").write_text(
                    json.dumps({"summary": s, "rows": rows}, indent=2), encoding="utf-8")
            failing = [r["request_id"] for r in rows
                       if False in (r["behaviour_ok"], r["workshop_ok"], r["faithful"])]
            print(f"{name:8s} behaviour {s['behaviour_accuracy']:.3f}  "
                  f"workshop {s['workshop_accuracy']:.3f}  "
                  f"faithfulness {s['faithfulness']:.3f}  failing {failing}")


if __name__ == "__main__":
    main()
