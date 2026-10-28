"""
score_run — score a batch run (results/inbox_run.jsonl) against the labelled
inbox (data/labels_inbox.json or the held-out labels).

Three scores per request, matching the roadmap's Section 6.3 plan:

  1. behaviour   — the routed behaviour matches the label (Table 7 Kind);
  2. workshop    — for allocate/refuse/impossible, the chosen (or top
                   candidate) workshop matches the ground-truth list;
  3. faithfulness— every number in the explanation traces to the tool log
                   or the user's message (eval/faithfulness.py).

Latency comes from the run records when present (run_eval records it).

Usage:

    python eval/score_run.py                          # dev set, latest run
    python eval/score_run.py --labels data/labels_heldout.json \
                            --results results/heldout_run.jsonl
    python eval/score_run.py --out scores.json        # also write JSON

Exit code is 0 even when scores are low — this is a report, not a gate.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

try:
    from desk.config import DATA_DIR, RESULTS_DIR
    from eval.faithfulness import check_faithfulness
except ImportError:  # run directly as a script: python eval/score_run.py
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from desk.config import DATA_DIR, RESULTS_DIR
    from eval.faithfulness import check_faithfulness

DEFAULT_LABELS = DATA_DIR / "labels_inbox.json"
DEFAULT_RESULTS = RESULTS_DIR / "inbox_run.jsonl"


def load_labels(path):
    return {row["request_id"]: row for row in
            json.loads(Path(path).read_text(encoding="utf-8"))}


def load_records(path):
    """Run records keyed by request_id (the meta line has none and is skipped)."""
    records = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if "request_id" in row:
            records[row["request_id"]] = row
    return records


def _actual_workshop(record):
    """Chosen workshop if the decision committed one, else the top candidate."""
    if record.get("chosen"):
        return record["chosen"]["workshop_id"]
    candidates = record.get("candidates") or []
    return candidates[0]["workshop_id"] if candidates else None


def score_run(labels_path=DEFAULT_LABELS, results_path=DEFAULT_RESULTS):
    labels = load_labels(labels_path)
    records = load_records(results_path)

    rows = []
    per_kind = defaultdict(lambda: {"n": 0, "behaviour_ok": 0})
    latencies = []
    for req_id, label in labels.items():
        rec = records.get(req_id)
        kind = label["kind"]
        per_kind[kind]["n"] += 1
        row = {"request_id": req_id, "kind": kind,
               "expected": label["behaviour"], "actual": None,
               "behaviour_ok": False, "workshop_ok": None,
               "faithful": None, "violations": [], "latency_s": None}
        if rec is None:
            row["error"] = "no record in run"
            rows.append(row)
            continue
        row["actual"] = rec.get("behaviour")
        row["latency_s"] = rec.get("latency_s")
        if row["latency_s"] is not None:
            latencies.append(row["latency_s"])
        if rec.get("error"):
            row["error"] = rec["error"]
            rows.append(row)
            continue

        row["behaviour_ok"] = (row["actual"] == label["behaviour"])
        per_kind[kind]["behaviour_ok"] += row["behaviour_ok"]

        if label["workshop"]:
            actual_w = _actual_workshop(rec)
            row["workshop_ok"] = actual_w in label["workshop"]

        report = check_faithfulness(rec.get("explanation", ""),
                                    rec.get("tool_log", []),
                                    rec.get("raw", ""))
        row["faithful"] = report.ok
        row["violations"] = report.violations
        rows.append(row)

    scored = [r for r in rows if not r.get("error")]
    n = len(rows)
    summary = {
        "labels": str(labels_path), "results": str(results_path),
        "n_requests": n,
        "errors": n - len(scored),
        "completion_rate": round(len(scored) / n, 3) if n else None,
        "overall_behaviour_accuracy": round(sum(r["behaviour_ok"] for r in scored) / n, 3) if n else None,
        "successful_behaviour_accuracy": round(sum(r["behaviour_ok"] for r in scored) / len(scored), 3) if scored else None,
        "overall_faithfulness": round(sum(1 for r in scored if r["faithful"]) / n, 3) if n else None,
        "behaviour_accuracy": round(sum(r["behaviour_ok"] for r in scored)
                                    / n, 3) if n else None,
        "workshop_accuracy": round(
            sum(1 for r in scored if r["workshop_ok"])
            / sum(1 for label in labels.values() if label["workshop"]), 3)
            if any(label["workshop"] for label in labels.values()) else None,
        "faithfulness": round(sum(1 for r in scored if r["faithful"])
                              / n, 3) if n else None,
        "mean_latency_s": round(sum(latencies) / len(latencies), 2)
                          if latencies else None,
        "per_kind_behaviour": {
            kind: {"n": v["n"],
                   "accuracy": round(v["behaviour_ok"] / v["n"], 3)}
            for kind, v in sorted(per_kind.items())},
    }
    return rows, summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", default=str(DEFAULT_LABELS))
    parser.add_argument("--results", default=str(DEFAULT_RESULTS))
    parser.add_argument("--out", default=None, help="optional JSON output path")
    args = parser.parse_args()

    rows, summary = score_run(args.labels, args.results)

    print(f"\n{'req':<5}{'kind':<13}{'expected':<11}{'actual':<11}"
          f"{'behav':<6}{'workshop':<9}{'faith':<6}{'lat(s)':<8}violations")
    for r in rows:
        print(f"{r['request_id']:<5}{r['kind']:<13}"
              f"{str(r['expected']):<11}{str(r['actual']):<11}"
              f"{'PASS' if r['behaviour_ok'] else 'FAIL':<6}"
              f"{('PASS' if r['workshop_ok'] else 'FAIL') if r['workshop_ok'] is not None else '-':<9}"
              f"{('PASS' if r['faithful'] else 'FAIL') if r['faithful'] is not None else '-':<6}"
              f"{str(r.get('latency_s')):<8}"
              f"{', '.join(r['violations']) if r['violations'] else ''}"
              f"{r.get('error', '')}")

    print("\n=== summary ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.out:
        Path(args.out).write_text(
            json.dumps({"summary": summary, "rows": rows},
                       ensure_ascii=False, indent=2),
            encoding="utf-8")
        print(f"written to {args.out}")


if __name__ == "__main__":
    main()
