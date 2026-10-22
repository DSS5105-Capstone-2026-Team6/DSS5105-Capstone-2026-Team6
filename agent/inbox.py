"""
inbox — run the 30 dispatch requests through the agent and record the results.

The inbox file (data/dispatch_requests.txt) is the evaluation input: it is
deliberately not clean, so lines are passed to the agent verbatim — only the
envelope "R07 [08:23] Ravi: <text>" is parsed, for record-keeping. Ground
truth lives in the roadmap's labelled table and is applied afterwards, when
scoring; it never enters the prompt.

Usage:

    uv run python -m agent.inbox                 # all 30 requests
    uv run python -m agent.inbox --limit 3       # smoke test
    uv run python -m agent.inbox --only R08 R20  # specific requests

Output: one JSON object per line in the output file (default
results/inbox_run.jsonl): {"request_id", "speaker", "raw", "reply",
"tool_log"}. The tool log is what the faithfulness checker scores against.
"""

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

try:
    from .lookup_order import OrderStore
    from .llm import DispatchAgent
except ImportError:  # run directly as a script: python agent/inbox.py
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from agent.lookup_order import OrderStore
    from agent.llm import DispatchAgent

INBOX_PATH = Path(__file__).parent.parent / "data" / "dispatch_requests.txt"
DEFAULT_OUT = Path(__file__).parent.parent / "results" / "inbox_run.jsonl"

ENVELOPE = re.compile(r"^(R\d{2}) \[(\d{2}:\d{2})\] ([^:]+): (.*)$")


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


def run_inbox(out_path=DEFAULT_OUT, limit=None, only=None, model=None):
    requests = parse_inbox()
    if only:
        requests = [r for r in requests if r["request_id"] in set(only)]
    if limit:
        requests = requests[:limit]

    agent = DispatchAgent(model=model) if model else DispatchAgent()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"meta": {"model": agent.model,
                                     "run_at": datetime.now().isoformat(timespec="seconds"),
                                     "n_requests": len(requests)}},
                           ensure_ascii=False) + "\n")
        for i, req in enumerate(requests, 1):
            agent.tool_log.clear()          # fresh conversation per request
            try:
                reply = agent.chat(req["text"])
            except Exception as exc:
                reply = f"AGENT ERROR: {exc}"
            record = {"request_id": req["request_id"], "speaker": req["speaker"],
                      "raw": req["text"], "reply": reply,
                      "tool_log": list(agent.tool_log)}
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()
            print(f"[{i}/{len(requests)}] {req['request_id']} done "
                  f"({len(agent.tool_log)} tool calls)")
    print(f"written to {out_path}")
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--only", nargs="+", default=None, metavar="R_ID")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--model", default=None)
    args = parser.parse_args()
    run_inbox(out_path=args.out, limit=args.limit, only=args.only, model=args.model)
