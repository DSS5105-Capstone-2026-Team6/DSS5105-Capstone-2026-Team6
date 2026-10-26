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


if __name__ == "__main__":
    print(f"PROJECT_ROOT       = {PROJECT_ROOT}")
    print(f"DATA_DIR           = {DATA_DIR}")
    print(f"RESULTS_DIR        = {RESULTS_DIR}")
    print(f"DEFAULT_AUDIT_PATH = {DEFAULT_AUDIT_PATH}")
    print(f"DEFAULT_MODEL      = {DEFAULT_MODEL}")
    print(f"DEEPSEEK_BASE_URL  = {DEEPSEEK_BASE_URL}")
    print(f"MAX_TOOL_ROUNDS    = {MAX_TOOL_ROUNDS}")
