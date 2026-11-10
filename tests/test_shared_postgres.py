"""Opt-in PostgreSQL acceptance tests in a temporary, isolated schema.

Set DSS5105_RUN_CLOUD_TESTS=1 explicitly. The configured connection must be
able to create/drop its own temporary schema. Public application data is
never reset or modified by these tests. No model API or Telegram traffic.
"""
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from types import SimpleNamespace

import pytest

from desk.audit import AuditLog, StaleAllocation
from desk.budget import CallBudget, BudgetExceeded
from desk.performance import PerformanceStore
from desk.register import OrderStore, WorkshopStore
from desk.storage import Database, database_setting

pytestmark = pytest.mark.skipif(
    os.environ.get('DSS5105_RUN_CLOUD_TESTS') != '1',
    reason='Cloud checks require explicit opt-in and local database credentials.')


@pytest.fixture
def cloud(monkeypatch):
    url = database_setting('DISPATCH_DATABASE_URL')
    assert url, 'Configure the local database connection first.'
    monkeypatch.setattr('desk.storage.database_url', lambda: url)
    monkeypatch.delenv('DISPATCH_DATABASE_SCHEMA', raising=False)
    root = Database(url=url)
    schema = 'dss5105_test_' + uuid4().hex
    with root.connect() as connection:
        connection.execute('CREATE SCHEMA ' + schema)
        sql = (Path(__file__).parents[1] / 'database/supabase_schema.sql').read_text()
        # No parameters here: execute the trusted migration as a single script.
        connection.connection.execute(sql.replace('public.', schema + '.')
                                      .replace("'public'", "'" + schema + "'"))
    monkeypatch.setenv('DISPATCH_DATABASE_SCHEMA', schema)
    try:
        yield schema
    finally:
        with root.connect() as connection:
            connection.execute('DROP SCHEMA ' + schema + ' CASCADE')


def stores():
    workshops = WorkshopStore()
    queues = {wid: w.queue0 for wid, w in workshops.workshops.items()}
    return AuditLog(initial_queues=queues), workshops


def test_two_clients_share_records_queues_and_duplicate_protection(cloud):
    web, workshops = stores()
    bot, _ = stores()
    order = OrderStore().by_id('ORD-063')
    old_version = bot.version
    record = web.allocate(order, workshops.workshops['W6'], committed_by='web',
                          expected_version=old_version)
    assert bot.load_all()[0].record_id == record.record_id
    assert bot.queues() == web.queues()
    with pytest.raises(ValueError, match='already committed'):
        bot.allocate(order, workshops.workshops['W6'], committed_by='bot')
    another = OrderStore().by_id('ORD-041')
    with pytest.raises(StaleAllocation):
        bot.allocate(another, workshops.workshops['W6'], committed_by='bot',
                     expected_version=old_version)
    bot.allocate(another, workshops.workshops['W6'], committed_by='bot',
                 expected_version=bot.version)
    assert len(web.load_all()) == 2
    assert web.queues() == bot.queues()


def test_concurrent_confirmations_record_only_one_allocation(cloud):
    web, workshops = stores()
    bot, _ = stores()
    order = OrderStore().by_id('ORD-063')
    def allocate(ledger):
        try:
            ledger.allocate(order, workshops.workshops['W6'], committed_by='test')
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(2) as pool:
        assert sum(pool.map(allocate, [web, bot])) == 1
    assert len(web.load_all()) == 1


def test_transaction_failure_rolls_back_whole_split(cloud):
    ledger, workshops = stores()
    order = OrderStore().by_id('ORD-063')
    before = ledger.queues()
    broken = SimpleNamespace(workshop_id='W2', capacity=0, defect_rate=.03)
    with pytest.raises(ZeroDivisionError):
        ledger.allocate_split(order, [(workshops.workshops['W6'], 50), (broken, 50)],
                              committed_by='test')
    assert ledger.load_all() == []
    assert ledger.queues() == before


def test_performance_and_usage_are_shared(cloud):
    web = PerformanceStore()
    bot = PerformanceStore()
    with ThreadPoolExecutor(3) as pool:
        list(pool.map(lambda _: PerformanceStore().observe(
            'W6', 400, '2026-04-10', '2026-04-11'), range(3)))
    assert web.learned('W6') == bot.learned('W6')
    assert bot.learned('W6')['observations'] == 3
    CallBudget().reserve(limits=[(3600, 1)])
    with pytest.raises(BudgetExceeded):
        CallBudget().reserve(limits=[(3600, 1)])


def test_reset_archives_allocations_and_preserves_budget(cloud):
    ledger, workshops = stores()
    ledger.allocate(OrderStore().by_id('ORD-063'), workshops.workshops['W6'],
                    committed_by='test')
    old_version = ledger.version
    CallBudget().reserve(limits=[(3600, 1)])
    ledger.reset()
    assert ledger.load_all() == []
    assert ledger.version != old_version
    with ledger.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM allocation_archive').fetchone()[0] == 1
    with pytest.raises(BudgetExceeded):
        CallBudget().reserve(limits=[(3600, 1)])
