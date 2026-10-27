"""Provider selection: DeepSeek / OpenAI / Claude presets drive one OpenAI-
compatible client — plus one failure case per assumption."""

import pytest

from desk.agent import DispatchAgent, load_api_key
from desk.config import DEFAULT_PROVIDER, PROVIDERS


def test_three_providers_defined():
    assert set(PROVIDERS) == {"deepseek", "openai", "anthropic"}
    for spec in PROVIDERS.values():
        assert spec["models"] and spec["key_vars"] and spec["label"]


def test_agent_defaults_to_deepseek():
    agent = DispatchAgent(api_key="test-key")
    assert agent.provider == DEFAULT_PROVIDER == "deepseek"
    assert agent.model == "deepseek-chat"
    assert str(agent.client.base_url).startswith("https://api.deepseek.com")


def test_agent_openai_uses_sdk_default_base_url():
    agent = DispatchAgent(provider="openai", api_key="test-key")
    assert agent.model == "gpt-6.1-terra"
    assert str(agent.client.base_url).startswith("https://api.openai.com")


def test_agent_anthropic_openai_compatible_endpoint():
    agent = DispatchAgent(provider="anthropic", api_key="test-key",
                          model="claude-sonnet-5-5")
    assert agent.model == "claude-sonnet-5-5"
    assert str(agent.client.base_url).startswith("https://api.anthropic.com")


def test_model_override_wins():
    agent = DispatchAgent(provider="deepseek", api_key="test-key",
                          model="deepseek-reasoner")
    assert agent.model == "deepseek-reasoner"


def test_unknown_provider_fails():
    with pytest.raises(KeyError):
        DispatchAgent(provider="cohere", api_key="test-key")


def test_missing_key_raises_with_provider_hint(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    for var in list(__import__("os").environ):
        if "DEEPSEEK" in var.upper():
            monkeypatch.delenv(var, raising=False)
    with pytest.raises(RuntimeError, match="Anthropic"):
        load_api_key("anthropic", env_path=tmp_path / "nope.env")
