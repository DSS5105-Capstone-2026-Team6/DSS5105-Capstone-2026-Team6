"""
run_full120.py - rerun data/dispatch_requests_full120.txt as a timeline
(stages on + periodic shocks), score it, and break the errors down by
whether the request names an order that is COMPLETE in the register.

Same logic as notebooks/full120_timeline_shock.ipynb, plus four fixes:
  * the API budget is raised with a hard override (the notebook used
    setdefault, so the 200/h value in .env stopped the run near F058);
  * a resumed run restores each workshop's queue from the rows already
    done (the notebook restarted with empty queues);
  * a fresh SQLite ledger per run, so old commits do not leak in;
  * each workshop keeps its own register status between days (the
    notebook re-opened every SUSPENDED shop, including OldMill).

Usage (from the repo root, with OPENAI_API_KEY in .env):
    python eval/run_full120.py                  # full run, OpenAI (default)
    python eval/run_full120.py --limit 10       # quick smoke test
    python eval/run_full120.py --provider deepseek
    python eval/run_full120.py --score-only     # re-score an existing run file
Interrupted? Run the same command again: finished rows are skipped.

Outputs in results/full120/:
    full120_<tag>.jsonl         one decision per request
    full120_<tag>_scores.json   all numbers + per-request table
    full120_<tag>_summary.md    paste-ready summary for the README
"""

import argparse
import csv
import json
import os
import re
import sys
import tempfile
import time
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path.cwd()
if not (ROOT / "desk").is_dir() and (ROOT.parent / "desk").is_dir():
    ROOT = ROOT.parent
if not (ROOT / "desk").is_dir():
    sys.exit("Run this from the repo root (the folder that has desk/ and data/).")
sys.path.insert(0, str(ROOT))

ap = argparse.ArgumentParser()
ap.add_argument("--provider", default="openai", choices=["deepseek", "openai", "anthropic"])
ap.add_argument("--limit", type=int, default=120)
ap.add_argument("--seed", type=int, default=5105)
ap.add_argument("--tag", default=None, help="output name; default rerun_<YYYYMMDD>_<provider>")
ap.add_argument("--score-only", action="store_true")
args = ap.parse_args()

TAG = args.tag or f"rerun_{date.today():%Y%m%d}_{args.provider}"
INBOX = ROOT / "data" / "dispatch_requests_full120.txt"
LABELS = ROOT / "data" / "f_heldout.json"
ORDERS = ROOT / "data" / "orders.csv"
OUTDIR = ROOT / "results" / "full120"
OUTDIR.mkdir(parents=True, exist_ok=True)
OUT = OUTDIR / f"full120_{TAG}.jsonl"
SCORES = OUTDIR / f"full120_{TAG}_scores.json"
SUMMARY = OUTDIR / f"full120_{TAG}_summary.md"

# --- environment: set BEFORE importing desk -------------------------------
os.environ["API_CALLS_PER_HOUR"] = "5000"      # hard override, not setdefault
os.environ["API_CALLS_PER_DAY"] = "20000"
os.environ.pop("DISPATCH_DATABASE_URL", None)   # never write to the shared cloud ledger
_tmpdb = Path(tempfile.mkdtemp(prefix="full120_")) / "ledger.sqlite3"
os.environ["DISPATCH_DB_PATH"] = str(_tmpdb)

from desk import config                           # noqa: E402
from desk.register import WorkshopStore           # noqa: E402
from eval.run_eval import parse_inbox             # noqa: E402
from eval.shock import build_calendar, shock_on   # noqa: E402

DAY0 = date(2026, 1, 1)
STAGES = True
SENT = re.compile(r"\[Sent: (\d{4}-\d{2}-\d{2})\]\s*$")
ORD = re.compile(r"ORD-\d{3}", re.I)


def sent_date(text):
    m = SENT.search(text)
    return date.fromisoformat(m.group(1)) if m else DAY0


config.set_as_of(DAY0)
requests = parse_inbox(INBOX)[: args.limit]
requests.sort(key=lambda r: sent_date(r["text"]))
labels = {l["request_id"]: l for l in json.loads(LABELS.read_text(encoding="utf-8"))}
_ws = WorkshopStore(stages=STAGES)
active = [w.workshop_id for w in _ws.workshops.values() if w.status == "ACTIVE"]
CALENDAR = build_calendar(active, seed=args.seed)


# --- run --------------------------------------------------------------------
def run():
    from desk.desk import DispatchDesk
    from desk.contracts import Behaviour, to_dict

    class TimelineState:
        def __init__(self):
            self.queues = {}

    desk = DispatchDesk(stages=STAGES, provider=args.provider)
    # Counterfactual, as in the notebook: the F-series orders are COMPLETE
    # in the register (they were finished in-house). The replay asks "what
    # if they had been outsourced on the sent date", so they are reset to
    # live work; otherwise the desk correctly refuses completed orders.
    for rec in desk.orders.orders:
        rec["status"] = "IN_PROGRESS"
        rec["completed_date"] = None
        rec["days_late"] = 0
        if rec.get("current_stage") == "COMPLETE":
            rec["current_stage"] = None
    desk.state = TimelineState()
    queue_free = {wid: w.queue0 for wid, w in desk.workshops.workshops.items()}
    original_status = {wid: w.status for wid, w in desk.workshops.workshops.items()}

    done = {}
    if OUT.exists():
        for line in OUT.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if "request_id" in row and "error" not in row:
                    done[row["request_id"]] = row
    # resume fix: replay the queue growth of rows already done
    for row in done.values():
        c = row.get("committed")
        if c:
            queue_free[c["workshop_id"]] = max(queue_free[c["workshop_id"]], c["queue_free_after"])
    if done:
        print(f"resuming: {len(done)} rows already done")

    t_start = time.perf_counter()
    with OUT.open("a", encoding="utf-8") as f:
        for i, req in enumerate(requests, 1):
            if req["request_id"] in done:
                continue
            sent = sent_date(req["text"])
            day = (sent - DAY0).days
            config.set_as_of(sent)
            desk.state.queues = {w: max(0.0, queue_free[w] - day) for w in queue_free}
            closure = shock_on(day, CALENDAR)
            # restore each workshop's own status, then apply today's closure
            # (the notebook re-opened every SUSPENDED shop, incl. OldMill)
            for wid, w in desk.workshops.workshops.items():
                w.status = original_status[wid]
            if closure:
                desk.workshops.workshops[closure["target"]].status = "SUSPENDED"

            record = {"request_id": req["request_id"], "speaker": req["speaker"],
                      "raw": req["text"], "sent_date": sent.isoformat(),
                      "shock_target": closure["target"] if closure else None}
            decision = None
            for attempt in (1, 2):                      # one retry on API errors
                desk.agent.new_conversation()
                t0 = time.perf_counter()
                try:
                    decision = desk.handle_message(req["text"], requester=req["speaker"],
                                                   request_id=req["request_id"])
                    record.update(latency_s=round(time.perf_counter() - t0, 2), **to_dict(decision))
                    record.pop("error", None)
                    break
                except Exception as exc:              # noqa: BLE001
                    record["error"] = f"AGENT ERROR: {exc}"
                    time.sleep(3)

            if (decision is not None and decision.behaviour is Behaviour.ALLOCATE
                    and decision.chosen is not None and decision.parsed.pieces):
                wid = decision.chosen.workshop_id
                w = desk.workshops.workshops[wid]
                start = max(day, queue_free[wid])
                work = int(decision.parsed.pieces) / w.capacity * (1 + 0.5 * w.defect_rate)
                finish = start + work
                if closure and closure["target"] == wid:
                    if closure["start"] <= start < closure["end"]:
                        finish = closure["end"] + work
                    elif start < closure["start"] < finish:
                        finish += closure["end"] - closure["start"]
                queue_free[wid] = finish
                record["committed"] = {"workshop_id": wid, "queue_free_after": round(finish, 2)}

            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()
            elapsed = time.perf_counter() - t_start
            print(f"[{i}/{len(requests)}] {req['request_id']} {sent} "
                  f"{'SHOCK:' + closure['target'] if closure else '-':<9} "
                  f"{record.get('behaviour', record.get('error', '?'))}  "
                  f"({elapsed/60:.1f} min)")


# --- score + completed-order analysis --------------------------------------
def score():
    orders = {r["order_id"]: r for r in csv.DictReader(ORDERS.open(encoding="utf-8"))}
    ws = WorkshopStore(stages=STAGES)
    records = {}
    for line in OUT.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            records[r["request_id"]] = r          # last row wins (retries)

    def order_group(req_id, raw):
        oid = (labels.get(req_id) or {}).get("order_id")
        ids = ORD.findall(raw or "")
        oid = (oid or (ids[0] if ids else None))
        if not oid:
            return "no order id", None, None
        oid = oid.upper()
        o = orders.get(oid)
        if o is None:
            return "unknown order id", oid, None
        if o["status"] == "COMPLETE":
            return "order COMPLETE in register", oid, o.get("completed_date")
        return "order open in register", oid, None

    def actual_w(rec):
        if rec.get("chosen"):
            return rec["chosen"]["workshop_id"]
        c = rec.get("candidates") or []
        return c[0]["workshop_id"] if c else None

    rows = []
    for req in requests:
        rid = req["request_id"]
        lab = labels.get(rid, {})
        rec = records.get(rid, {})
        grp, oid, cdate = order_group(rid, req["text"])
        exp_w = {ws.resolve(w) or w for w in (lab.get("workshop") or [])}
        got_w = actual_w(rec) if rec else None
        row = {"request_id": rid, "kind": lab.get("kind"), "expected": lab.get("behaviour"),
               "got": rec.get("behaviour"), "error": rec.get("error"),
               "behaviour_ok": (not rec.get("error")) and rec.get("behaviour") == lab.get("behaviour"),
               "workshop_expected": sorted(exp_w), "workshop_got": got_w,
               "workshop_ok": (got_w in exp_w) if (exp_w and lab.get("behaviour") == "allocate") else None,
               "order_id": oid, "order_group": grp, "register_completed_date": cdate,
               "sent_date": sent_date(req["text"]).isoformat(),
               "completed_after_sent": (cdate is not None and cdate > sent_date(req["text"]).isoformat()),
               "shock_target": rec.get("shock_target"), "latency_s": rec.get("latency_s"),
               "message": req["text"]}
        rows.append(row)

    def acc(sel):
        n = len(sel)
        k = sum(r["behaviour_ok"] for r in sel)
        return {"ok": k, "n": n, "acc": round(k / n, 3) if n else None}

    by_kind = {k: acc([r for r in rows if r["kind"] == k]) for k in sorted({r["kind"] for r in rows if r["kind"]})}
    by_exp = {k: acc([r for r in rows if r["expected"] == k]) for k in sorted({r["expected"] for r in rows if r["expected"]})}
    by_group = {g: acc([r for r in rows if r["order_group"] == g]) for g in sorted({r["order_group"] for r in rows})}
    ws_rows = [r for r in rows if r["workshop_ok"] is not None]
    confusion = Counter((r["expected"], r["got"] or "ERROR") for r in rows if not r["behaviour_ok"])
    lat = [r["latency_s"] for r in rows if r["latency_s"] is not None]
    summary = {
        "tag": TAG, "provider": args.provider, "n": len(rows),
        "behaviour": acc(rows),
        "behaviour_excl_errors": acc([r for r in rows if not r["error"]]),
        "api_errors": [r["request_id"] for r in rows if r["error"]],
        "workshop": {"ok": sum(r["workshop_ok"] for r in ws_rows), "n": len(ws_rows)},
        "by_kind": by_kind, "by_expected": by_exp, "by_order_group": by_group,
        "complete_orders_completed_after_sent":
            sum(r["completed_after_sent"] for r in rows if r["order_group"].startswith("order COMPLETE")),
        "confusion_failures": {f"{e} -> {g}": c for (e, g), c in confusion.most_common()},
        "mean_latency_s": round(sum(lat) / len(lat), 2) if lat else None,
    }
    SCORES.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")

    # markdown summary
    L = [f"### Full-120 timeline rerun ({TAG})", "",
         f"Provider `{args.provider}`, stages on, periodic shocks (seed {args.seed}), labels `data/f_heldout.json`.", "",
         f"- Behaviour accuracy: **{summary['behaviour']['ok']}/{summary['behaviour']['n']} = {summary['behaviour']['acc']}**"
         f" ({len(summary['api_errors'])} API errors: {', '.join(summary['api_errors']) or 'none'})",
         f"- Workshop accuracy (allocate rows with a labelled shop): {summary['workshop']['ok']}/{summary['workshop']['n']}",
         f"- Mean latency: {summary['mean_latency_s']} s", "",
         "| Expected behaviour | Correct |", "|---|---|"]
    L += [f"| {k} | {v['ok']}/{v['n']} |" for k, v in by_exp.items()]
    L += ["", "| Order named in the request | Requests | Correct |", "|---|---|---|"]
    L += [f"| {g} | {v['n']} | {v['ok']}/{v['n']} ({v['acc']}) |" for g, v in by_group.items()]
    L += ["", f"{summary['complete_orders_completed_after_sent']} of the COMPLETE orders were completed "
          "after the request's sent date.", "", "| Failure (expected -> got) | Count |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in summary["confusion_failures"].items()]
    L += ["", "| Request | Kind | Expected | Got | Order | Register status |", "|---|---|---|---|---|---|"]
    for r in rows:
        if not r["behaviour_ok"]:
            st = "COMPLETE" if r["order_group"].startswith("order COMPLETE") else r["order_group"]
            L.append(f"| {r['request_id']} | {r['kind']} | {r['expected']} | {r['got'] or 'ERROR'} | {r['order_id'] or '-'} | {st} |")
    SUMMARY.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))
    print(f"\nwrote {OUT.name}, {SCORES.name}, {SUMMARY.name} in {OUTDIR}")


if __name__ == "__main__":
    if not args.score_only:
        print(f"{len(requests)} requests, provider {args.provider}, output {OUT}")
        run()
    score()
