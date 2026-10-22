"""
llm — the DeepSeek intake component.

The LLM parses the chat message and writes the reply; every number comes from
a tool call (roadmap §1.4). Settings: temperature 0, every tool call and
result appended to self.tool_log so the faithfulness checker can verify that
each number in the reply traces to a tool output.

DeepSeek exposes an OpenAI-compatible API, so this uses the openai SDK with
base_url https://api.deepseek.com. OPENAI_API_KEY (this project stores the DeepSeek key under that name, since
DeepSeek's API is OpenAI-compatible).

Run directly for a manual smoke test:

    uv run python -m agent.llm "Ravi: ORD-063 — 100 cardigans, make Apr 29."
"""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from .lookup_order import OrderStore
from .registry import dispatch_tool, tool_schemas

PROJECT_ROOT = Path(__file__).parent.parent
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
MAX_TOOL_ROUNDS = 8

SYSTEM_PROMPT = """You are the intake agent of a knitwear subcontracting dispatch desk.

Rules:
- Never perform arithmetic. Every number (dates, queues, costs, capacities)
  must come from a tool output; quote only numbers the tools returned.
- If a request is ambiguous or missing information, ask a clarifying question
  instead of guessing.
- If the suggested workshop cannot take the batch, refuse with the reason the
  tools give and offer the best alternative.
- Always record who imposed a constraint when one is stated.
"""


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
    """Chat loop: model -> tool calls -> tool results -> reply."""

    def __init__(self, model=DEFAULT_MODEL, stages=False, api_key=None):
        self.client = OpenAI(api_key=api_key or load_api_key(),
                             base_url=DEEPSEEK_BASE_URL)
        self.model = model
        self.store = OrderStore(stages=stages)
        self.tool_log = []   # [{"tool", "arguments", "result"}] per call

    def chat(self, message):
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": message},
        ]
        for _ in range(MAX_TOOL_ROUNDS):
            resp = self.client.chat.completions.create(
                model=self.model, messages=messages,
                tools=tool_schemas(), temperature=0)
            msg = resp.choices[0].message
            messages.append(msg)
            if not msg.tool_calls:
                return msg.content
            for call in msg.tool_calls:
                result = dispatch_tool(call.function.name,
                                       json.loads(call.function.arguments or "{}"),
                                       store=self.store)
                self.tool_log.append({"tool": call.function.name,
                                      "arguments": json.loads(call.function.arguments or "{}"),
                                      "result": result})
                messages.append({"role": "tool", "tool_call_id": call.id,
                                 "content": json.dumps(result, default=str)})
        raise RuntimeError(f"tool loop did not converge in {MAX_TOOL_ROUNDS} rounds")


if __name__ == "__main__":
    agent = DispatchAgent()
    text = " ".join(sys.argv[1:]) or "R08: send ORD-073 to FreshStart."
    print(agent.chat(text))
    print(f"\n--- tool log ({len(agent.tool_log)} calls) ---")
    for entry in agent.tool_log:
        print(entry["tool"], entry["arguments"])
