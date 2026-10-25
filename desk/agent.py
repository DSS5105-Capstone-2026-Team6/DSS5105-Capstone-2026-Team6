"""
agent — the DeepSeek intake component.

The LLM parses the chat message and writes the reply; every number comes from
a tool call (roadmap §1.4). Settings: temperature 0, every tool call and
result appended to self.tool_log so the faithfulness checker can verify that
each number in the reply traces to a tool output.

DeepSeek exposes an OpenAI-compatible API, so this uses the openai SDK with
base_url https://api.deepseek.com. OPENAI_API_KEY (this project stores the DeepSeek key under that name, since
DeepSeek's API is OpenAI-compatible).

The system prompt lives in desk/prompts/system.txt (plain text, read at
import time) so prompt tuning needs no code changes.

Run directly for a manual smoke test:

    uv run python desk/agent.py "Ravi: ORD-063 — 100 cardigans, make Apr 29."
"""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

try:
    from desk.config import (DEFAULT_MODEL, DEEPSEEK_BASE_URL,
                             MAX_TOOL_ROUNDS, PROJECT_ROOT)
    from desk.register import OrderStore, WorkshopStore
    from desk.tools import dispatch_tool, tool_schemas
except ImportError:  # run directly as a script: python desk/agent.py
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from desk.config import (DEFAULT_MODEL, DEEPSEEK_BASE_URL,
                             MAX_TOOL_ROUNDS, PROJECT_ROOT)
    from desk.register import OrderStore, WorkshopStore
    from desk.tools import dispatch_tool, tool_schemas

SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "system.txt"
                 ).read_text(encoding="utf-8")


def load_api_key(env_path=PROJECT_ROOT / ".env"):
    """Load the API key from .env: prefer a *DEEPSEEK* variable, fall back to
    OPENAI_API_KEY (this project stores the DeepSeek key under that name,
    since DeepSpeak's API is OpenAI-compatible)."""
    load_dotenv(env_path)
    for var, value in os.environ.items():
        if "DEEPSEEK" in var.upper() and value:
            return value
    value = os.environ.get("OPENAI_API_KEY")
    if value:
        return value
    raise RuntimeError(
        f"No API key found: expected a *DEEPSEEK* or OPENAI_API_KEY variable "
        f"in {env_path}")


class DispatchAgent:
    """Chat loop: model -> tool calls -> tool results -> reply.

    Every call is recorded in self.tool_log (for the faithfulness checker
    and the desk's decision labelling). Pass verbose=True to chat() to
    watch each round live on stdout: which tool the model picked, the
    arguments, and a truncated result."""

    def __init__(self, model=DEFAULT_MODEL, stages=False, api_key=None):
        self.client = OpenAI(api_key=api_key or load_api_key(),
                             base_url=DEEPSEEK_BASE_URL)
        self.model = model or DEFAULT_MODEL
        self.store = OrderStore(stages=stages)
        self.workshops = WorkshopStore(stages=stages)
        self.desk = None   # set by desk.DispatchDesk; tools then share its state
        self.tool_log = []   # [{"tool", "arguments", "result"}] per call

    def chat(self, message, verbose=False):
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": message},
        ]
        for round_no in range(1, MAX_TOOL_ROUNDS + 1):
            resp = self.client.chat.completions.create(
                model=self.model, messages=messages,
                tools=tool_schemas(), temperature=0)
            msg = resp.choices[0].message
            messages.append(msg)
            if not msg.tool_calls:
                if verbose:
                    print(f"[round {round_no}] model replied (no tool call)")
                return msg.content
            for call in msg.tool_calls:
                arguments = json.loads(call.function.arguments or "{}")
                result = dispatch_tool(call.function.name, arguments,
                                       desk=self.desk)
                self.tool_log.append({"tool": call.function.name,
                                      "arguments": arguments,
                                      "result": result})
                messages.append({"role": "tool", "tool_call_id": call.id,
                                 "content": json.dumps(result, default=str)})
                if verbose:
                    rendered = json.dumps(result, default=str)
                    if len(rendered) > 240:
                        rendered = rendered[:240] + "…"
                    print(f"[round {round_no}] -> {call.function.name} {json.dumps(arguments)}")
                    print(f"           <- {rendered}")
        raise RuntimeError(f"tool loop did not converge in {MAX_TOOL_ROUNDS} rounds")


if __name__ == "__main__":
    # Usage:
    #   python desk/agent.py            -> run R08 from the real inbox
    #   python desk/agent.py R20        -> run request R20 from the inbox
    #   python desk/agent.py <text>     -> run the given message verbatim
    try:
        from eval.run_eval import parse_inbox
    except ImportError:  # run directly as a script: python desk/agent.py
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from eval.run_eval import parse_inbox

    arg = " ".join(sys.argv[1:])
    requests = parse_inbox()
    if not arg or arg.upper() in {r["request_id"] for r in requests}:
        req_id = arg.upper() or "R08"
        req = next(r for r in requests if r["request_id"] == req_id)
        text = req["text"]
        print(f"[{req['request_id']} {req['time']}] {req['speaker']}: {text}\n")
    else:
        text = arg

    agent = DispatchAgent()
    print(agent.chat(text, verbose=True))
    print(f"\n--- tool log ({len(agent.tool_log)} calls) ---")
    for entry in agent.tool_log:
        print(entry["tool"], entry["arguments"])
        rendered = json.dumps(entry["result"], default=str)
        if len(rendered) > 240:
            rendered = rendered[:240] + "…"
        print(f"    result: {rendered}")
