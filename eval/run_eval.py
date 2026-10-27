"""
run_eval — run the 30 dispatch requests through the agent and record the
results.

The inbox file (data/dispatch_requests.txt) is the evaluation input: it is
deliberately not clean, so lines are passed to the agent verbatim — only the
envelope "R07 [08:23] Ravi: <text>" is parsed, for record-keeping. Ground
truth lives in the roadmap's labelled table and is applied afterwards, when
scoring; it never enters the prompt.

Usage:

    python eval/run_eval.py                 # all 30 dev requests
    python eval/run_eval.py --limit 3       # smoke test
    python eval/run_eval.py --only R08 R20  # specific requests
    python eval/run_eval.py --only R08 -v   # also print each tool round
    python eval/run_eval.py --inbox data/dispatch_requests_heldout.txt \
        --out results/heldout_run.jsonl     # the held-out H01-H20 set,
                                            # then: score_run.py --labels
                                            # data/labels_heldout.json

Output: one JSON object per line in the output file (default
results/inbox_run.jsonl): the serialised Decision per request (behaviour,
parsed fields, candidates, explanation) plus the raw text. The tool log
inside is what the faithfulness checker scores against. State is NOT
committed during a batch run — confirmation is a UI action, so the chat-side
queues stay at the 1 April snapshot throughout.
"""

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

try:
    from desk.config import DATA_DIR, RESULTS_DIR
    from desk.desk import DispatchDesk
    from desk.contracts import to_dict
    from desk.chat_dump import ENVELOPE
except ImportError:  # run directly as a script: python eval/run_eval.py
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from desk.config import DATA_DIR, RESULTS_DIR
    from desk.desk import DispatchDesk
    from desk.contracts import to_dict
    from desk.chat_dump import ENVELOPE

INBOX_PATH = DATA_DIR / "dispatch_requests.txt"
DEFAULT_OUT = RESULTS_DIR / "inbox_run.jsonl"


def parse_inbox(path=INBOX_PATH):
    """Parse the inbox into [{"request_id", "time", "speaker", "text"}].
    Comment (#) and blank lines are skipped; the message text is kept verbatim."""
    requests = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = ENVELOPE.match(line)
        if m is None:
            raise ValueError(f"unparseable inbox line: {line!r}")
        requests.append({"request_id": m.group(1), "time": m.group(2),
                         "speaker": m.group(3), "text": m.group(4)})
    return requests


def run_inbox(inbox_path=INBOX_PATH, out_path=DEFAULT_OUT, limit=None,
              only=None, model=None, provider=None, verbose=False):
    requests = parse_inbox(inbox_path)
    if only:
        requests = [r for r in requests if r["request_id"] in set(only)]
    if limit:
        requests = requests[:limit]

    desk = DispatchDesk(model=model, provider=provider)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"meta": {"provider": desk.agent.provider,
                                     "model": desk.agent.model,
                                     "run_at": datetime.now().isoformat(timespec="seconds"),
                                     "n_requests": len(requests)}},
                           ensure_ascii=False) + "\n")
        for i, req in enumerate(requests, 1):
            try:
                if verbose:
                    print(f"\n===== {req['request_id']} [{req['time']}] "
                          f"{req['speaker']}: {req['text']}")
                desk.agent.new_conversation()   # each request stands alone
                t0 = time.perf_counter()
                decision = desk.handle_message(req["text"],
                                               requester=req["speaker"],
                                               request_id=req["request_id"],
                                               verbose=verbose)
                latency_s = round(time.perf_counter() - t0, 2)
                record = {"speaker": req["speaker"], "raw": req["text"],
                          "latency_s": latency_s, **to_dict(decision)}
                n_tools = len(decision.tool_log)
            except Exception as exc:
                record = {"request_id": req["request_id"], "speaker": req["speaker"],
                          "raw": req["text"], "error": f"AGENT ERROR: {exc}"}
                n_tools = 0
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()
            print(f"[{i}/{len(requests)}] {req['request_id']} done "
                  f"({n_tools} tool calls, "
                  f"{record.get('behaviour', record.get('error', '?'))})")
    print(f"written to {out_path}")
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--inbox", default=str(INBOX_PATH),
                        help="inbox file to run (e.g. data/dispatch_requests_"
                             "heldout.txt for the held-out H01–H20 set)")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--only", nargs="+", default=None, metavar="R_ID")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--model", default=None)
    parser.add_argument("--provider", default=None,
                        help="deepseek | openai | anthropic (default deepseek)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="print each request and every tool round live")
    args = parser.parse_args()
    run_inbox(inbox_path=args.inbox, out_path=args.out, limit=args.limit,
              only=args.only, model=args.model, provider=args.provider,
              verbose=args.verbose)
