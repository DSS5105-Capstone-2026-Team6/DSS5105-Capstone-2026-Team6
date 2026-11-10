"""Storage regressions that never contact a cloud service."""
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from desk.performance import PerformanceStore
from desk.storage import Database


def test_explicit_local_path_does_not_use_cloud_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr('desk.storage.database_url', lambda: 'postgresql://invalid/remote')
    db = Database(tmp_path / 'local.sqlite3')
    assert not db.is_postgres
    with db.connect() as connection:
        connection.execute('CREATE TABLE proof (value TEXT)')


def test_concurrent_returned_batches_preserve_all_observations(tmp_path):
    path = tmp_path / 'performance.sqlite3'
    PerformanceStore(path)
    def observe(_):
        return PerformanceStore(path).observe('W6', 400, '2026-04-10', '2026-04-11')
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(observe, range(4)))
    assert PerformanceStore(path).learned('W6')['observations'] == 4


def test_cloud_connection_failure_does_not_disclose_password(monkeypatch):
    import psycopg
    monkeypatch.setattr('desk.storage.database_setting', lambda _: '')
    db = Database(url='postgresql://user:private_password@host/db')
    with patch('psycopg.connect', side_effect=psycopg.OperationalError('private_password')):
        with pytest.raises(RuntimeError) as error:
            with db.connect():
                pass
    assert 'private_password' not in str(error.value)


def test_no_fallback_to_local_storage_when_cloud_is_unavailable(tmp_path, monkeypatch):
    import psycopg
    monkeypatch.setattr('desk.storage.database_setting', lambda _: '')
    monkeypatch.setenv('DISPATCH_DB_PATH', str(tmp_path / 'must_not_exist.sqlite3'))
    db = Database(url='postgresql://user@host/db')
    with patch('psycopg.connect', side_effect=psycopg.OperationalError()):
        with pytest.raises(RuntimeError):
            with db.connect():
                pass
    assert not (tmp_path / 'must_not_exist.sqlite3').exists()
