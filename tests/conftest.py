"""Keep pytest independent of developer credentials and operational state."""
import pytest


@pytest.fixture(autouse=True)
def offline_credentials_and_state(monkeypatch, tmp_path):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'offline-test-key')
    monkeypatch.setenv('DISPATCH_DB_PATH', str(tmp_path / 'runtime.sqlite3'))
