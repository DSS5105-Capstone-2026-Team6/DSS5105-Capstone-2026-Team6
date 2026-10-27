"""
agent — the LLM intake component.

The LLM parses the chat message and writes the reply; every number comes from
a tool call (roadmap §1.4). Settings: temperature 0, every tool call and
result appended to self.tool_log so the faithfulness checker can verify that
each number in the reply traces to a tool output.

The provider is selectable (desk/config.py PROVIDERS): DeepSeek, OpenAI (GPT)
and Anthropic (Claude) all expose an OpenAI-compatible API, so this one file
drives every provider through the openai SDK. The DeepSeek key may live under
OPENAI_API_KEY (this project's .env convention) — key resolution tries the
provider's key_vars in order, from the environment, st.secrets, then .env.

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
    from desk.config import (DEFAULT_PROVIDER, MAX_TOOL_ROUNDS, PROVIDERS,
                             PROJECT_ROOT)
    from desk.register import OrderStore, WorkshopStore
    from desk.tools import dispatch_tool, tool_schemas
except ImportError:  # run directly as a script: python desk/agent.py
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from desk.config import (DEFAULT_PROVIDER, MAX_TOOL_ROUNDS, PROVIDERS,
                             PROJECT_ROOT)
    from desk.register import OrderStore, WorkshopStore
    from desk.tools import dispatch_tool, tool_schemas

SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "system.txt"
                 ).read_text(encoding="utf-8")


def load_api_key(provider=DEFAULT_PROVIDER, env_path=PROJECT_ROOT / ".env"):
    """Resolve the API key for a provider. Lookup order:
    1. Process env vars (Streamlit Cloud injects Secrets here at runtime),
       trying the provider's key_vars in order. For deepseek any env var
       whose name contains DEEPSEEK also counts (legacy naming).
    2. st.secrets (explicit check, in case env injection is unavailable).
    3. Local .env file — optional, missing it is NOT an error on the cloud.
    """
    spec = PROVIDERS[provider]
    # 1) environment (works both locally after load_dotenv and on the cloud)
    if env_path.exists():          # .env is a local-dev convenience only
        load_dotenv(env_path)      # missing file -> skip silently
    for var in spec["key_vars"]:
        value = os.environ.get(var)
        if value:
            return value
    if provider == "deepseek":     # legacy: any *DEEPSEEK* variable
        for var, value in os.environ.items():
            if "DEEPSEEK" in var.upper() and value:
                return value

    # 2) st.secrets — Streamlit Cloud's canonical store
    try:
        import streamlit as st
        secrets = st.secrets
        for var in spec["key_vars"]:
            if secrets.get(var):
                return secrets[var]
        if provider == "deepseek":
            for var in secrets.keys():
                if "DEEPSEEK" in var.upper() and secrets[var]:
                    return secrets[var]
    except Exception:
        pass  # not running inside Streamlit (e.g. pytest, CLI smoke runs)

    # 3) nothing found — error message covers BOTH sources
    raise RuntimeError(
        f"No API key found for {spec['label']}. On Streamlit Cloud: app "
        f"Settings -> Secrets, add {spec['key_hint']}. "
        f"Locally: create {env_path} with the same variable.")



class DispatchAgent:
    """Chat loop: model -> tool calls -> tool results -> reply.

    Every call is recorded in self.tool_log (for the faithfulness checker
    and the desk's decision labelling). Pass verbose=True to chat() to
    watch each round live on stdout: which tool the model picked, the
    arguments, and a truncated result."""

    def __init__(self, model=None, stages=False, api_key=None,
                 provider=DEFAULT_PROVIDER):
        spec = PROVIDERS[provider]
        self.provider = provider
        self.client = OpenAI(api_key=api_key or load_api_key(provider),
                             base_url=spec["base_url"])   # None -> api.openai.com
        self.model = model or spec["models"][0][0]   # display list, api id
        self.store = OrderStore(stages=stages)
        self.workshops = WorkshopStore(stages=stages)
        self.desk = None   # set by desk.DispatchDesk; tools then share its state
        self.tool_log = []   # [{"tool", "arguments", "result"}] per call
        self.history = []    # the conversation so far (excl. system prompt)

    def new_conversation(self):
        """Forget the thread. Batch evaluation calls this between requests so
        each of the 30 inbox messages is handled independently (Risk 4)."""
        self.history = []

    def _trim_history(self, max_messages=40):
        """Keep the tail of the thread; cut only at a user message so no
        tool result is left orphaned from its assistant tool_calls."""
        while len(self.history) > max_messages:
            for i, m in enumerate(self.history):
                if i > 0 and m.get("role") == "user":
                    self.history = self.history[i:]
                    break
            else:
                self.history = self.history[len(self.history) - max_messages:]

    def chat(self, message, verbose=False):
        self.tool_log = []   # per message: route() and the faithfulness
                             # checker must never see a previous request's calls
        self.history.append({"role": "user", "content": message})
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, *self.history]
        # OpenAI reasoning models reject function tools on /v1/chat/completions
        # unless reasoning is switched off; DeepSeek and Claude don't need it
        extra = ({"reasoning_effort": "none"} if self.provider == "openai"
                 else {})
        for round_no in range(1, MAX_TOOL_ROUNDS + 1):
            resp = self.client.chat.completions.create(
                model=self.model, messages=messages,
                tools=tool_schemas(), temperature=0, **extra)
            msg = resp.choices[0].message
            messages.append(msg)
            if not msg.tool_calls:
                if verbose:
                    print(f"[round {round_no}] model replied (no tool call)")
                # persist the turn: everything since the last user message
                self.history.extend(messages[len(self.history) + 1:])
                self._trim_history()
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
    #   python desk/agent.py                  -> run R08 from the real inbox
    #   python desk/agent.py R20              -> run request R20 from the inbox
    #   python desk/agent.py R20 anthropic    -> same, with the Claude provider
    #   python desk/agent.py <text>           -> run the given message verbatim
    try:
        from eval.run_eval import parse_inbox
    except ImportError:  # run directly as a script: python desk/agent.py
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from eval.run_eval import parse_inbox

    args = sys.argv[1:]
    provider = None
    if args and args[-1].lower() in PROVIDERS:
        provider = args.pop().lower()
    arg = " ".join(args)
    requests = parse_inbox()
    if not arg or arg.upper() in {r["request_id"] for r in requests}:
        req_id = arg.upper() or "R08"
        req = next(r for r in requests if r["request_id"] == req_id)
        text = req["text"]
        print(f"[{req['request_id']} {req['time']}] {req['speaker']}: {text}\n")
    else:
        text = arg

    agent = DispatchAgent(provider=provider) if provider else DispatchAgent()
    print(agent.chat(text, verbose=True))
    print(f"\n--- tool log ({len(agent.tool_log)} calls) ---")
    for entry in agent.tool_log:
        print(entry["tool"], entry["arguments"])
        rendered = json.dumps(entry["result"], default=str)
        if len(rendered) > 240:
            rendered = rendered[:240] + "…"
        print(f"    result: {rendered}")
