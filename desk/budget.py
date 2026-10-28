"""Shared, transactional API-call budgets. Demo resets never clear this table."""
from contextlib import closing
import os
import sqlite3
import time
from pathlib import Path

from .config import RESULTS_DIR


class BudgetExceeded(RuntimeError):
    pass


class CallBudget:
    def __init__(self, path=None):
        self.path = Path(path or os.environ.get('DISPATCH_DB_PATH')
                         or RESULTS_DIR / 'audit_log.sqlite3')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=15)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS api_usage '
                       '(scope TEXT NOT NULL, at REAL NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS usage_scope_at ON api_usage(scope, at)')

    def reserve(self, *, scope='llm', limits=None, now=None):
        if limits is None:
            limits = [(3600, int(os.environ.get('API_CALLS_PER_HOUR', '200'))),
                      (86400, int(os.environ.get('API_CALLS_PER_DAY', '1000')))]
        now = time.time() if now is None else now
        with closing(sqlite3.connect(self.path, timeout=15)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            for seconds, maximum in limits:
                count = db.execute('SELECT COUNT(*) FROM api_usage WHERE scope=? AND at>?',
                                   (scope, now - seconds)).fetchone()[0]
                if maximum <= 0 or count >= maximum:
                    raise BudgetExceeded('Request limit reached. Please try again later.')
            db.execute('INSERT INTO api_usage VALUES (?, ?)', (scope, now))
            db.execute('DELETE FROM api_usage WHERE at<=?', (now - 86400,))
