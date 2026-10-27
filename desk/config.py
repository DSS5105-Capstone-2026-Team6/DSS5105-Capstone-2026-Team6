"""
config — the project's central constants: model, API and filesystem paths.

Everything that used to be computed as Path(__file__).parent.parent ... in
the individual modules lives here now, so the layout has a single place to
point at the data and results directories.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RESULTS_DIR = PROJECT_ROOT / "results"
DEFAULT_AUDIT_PATH = RESULTS_DIR / "audit_log.jsonl"

DEFAULT_MODEL = "deepseek-chat"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
MAX_TOOL_ROUNDS = 8

# LLM provider presets. All three expose an OpenAI-compatible API, so one
# SDK (openai) drives every provider: base_url None means the SDK default
# (api.openai.com). key_vars are the environment / st.secrets names tried
# in order when resolving the key.
PROVIDERS = {
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "key_vars": ("DEEPSEEK_API_KEY", "OPENAI_API_KEY"),
        "key_hint": 'DEEPSEEK_API_KEY = "sk-..."',
    },
    "openai": {
        "label": "OpenAI (GPT)",
        "base_url": "https://api.openai.com",                       # SDK default: api.openai.com
        "models": ["gpt-6.1-terra", "gpt-5.6-luna"],
        "key_vars": ("OPENAI_API_KEY",),
        "key_hint": 'OPENAI_API_KEY = "sk-..."',
    },
    "anthropic": {
        "label": "Anthropic (Claude)",
        "base_url": "https://api.anthropic.com/v1/",
        "models": ["claude-haiku-5-5", "claude-sonnet-5-5"],
        "key_vars": ("ANTHROPIC_API_KEY",),
        "key_hint": 'ANTHROPIC_API_KEY = "sk-ant-..."',
    },
}
DEFAULT_PROVIDER = "deepseek"


if __name__ == "__main__":
    print(f"PROJECT_ROOT       = {PROJECT_ROOT}")
    print(f"DATA_DIR           = {DATA_DIR}")
    print(f"RESULTS_DIR        = {RESULTS_DIR}")
    print(f"DEFAULT_AUDIT_PATH = {DEFAULT_AUDIT_PATH}")
    print(f"DEFAULT_MODEL      = {DEFAULT_MODEL}")
    print(f"DEEPSEEK_BASE_URL  = {DEEPSEEK_BASE_URL}")
    print(f"MAX_TOOL_ROUNDS    = {MAX_TOOL_ROUNDS}")
    for key, spec in PROVIDERS.items():
        print(f"provider {key:<10} base_url={spec['base_url']} models={spec['models']}")
