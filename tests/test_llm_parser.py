"""llm_parser must call the model the same way the agent does (OpenAI needs
reasoning_effort/max_completion_tokens) and never crash the UI on errors."""

from types import SimpleNamespace

from desk.agent import DispatchAgent
from desk.llm_parser import parse_message


class FakeCompletions:
    def __init__(self, content='{"orders": [], "intent": "other", "constraints": []}',
                 error=None):
        self.content, self.error, self.kwargs = content, error, None

    def create(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        msg = SimpleNamespace(content=self.content, tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def make_agent(provider, completions, tmp_path, monkeypatch):
    monkeypatch.setenv("DISPATCH_DB_PATH", str(tmp_path / "budget.sqlite3"))
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return DispatchAgent(provider=provider, client=client)


def test_openai_parse_sends_reasoning_off(tmp_path, monkeypatch):
    fake = FakeCompletions()
    agent = make_agent("openai", fake, tmp_path, monkeypatch)
    out = parse_message("ORD-041 needs a home today", agent)
    assert out["intent"] == "other"
    assert fake.kwargs["reasoning_effort"] == "none"
    assert "max_completion_tokens" in fake.kwargs
    assert "max_tokens" not in fake.kwargs


def test_deepseek_parse_has_no_reasoning_param(tmp_path, monkeypatch):
    fake = FakeCompletions()
    agent = make_agent("deepseek", fake, tmp_path, monkeypatch)
    parse_message("ORD-041", agent)
    assert "reasoning_effort" not in fake.kwargs
    assert "max_tokens" in fake.kwargs


def test_api_error_returns_error_dict(tmp_path, monkeypatch):
    fake = FakeCompletions(error=ValueError("400 bad request"))
    agent = make_agent("openai", fake, tmp_path, monkeypatch)
    out = parse_message("ORD-041", agent)
    assert "error" in out
