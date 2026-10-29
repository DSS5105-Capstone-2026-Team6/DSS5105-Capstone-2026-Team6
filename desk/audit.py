"""Transactional allocation ledger shared by every desk in this deployment.

Existing JSONL ledgers are imported once. SQLite is authoritative afterwards;
set DISPATCH_DB_PATH to a durable volume for persistence across redeployments.
"""
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .config import DEFAULT_AUDIT_PATH, CHAT_AS_OF
from .contracts import AllocationRecord, allocation_from_dict, to_dict

DEFAULT_PATH = DEFAULT_AUDIT_PATH


class StaleAllocation(ValueError):
    pass


class AuditLog:
    def __init__(self, path=DEFAULT_PATH, *, initial_queues=None):
        legacy = Path(path)
        configured = os.environ.get('DISPATCH_DB_PATH') if legacy == DEFAULT_PATH else None
        self.path = Path(configured) if configured else legacy.with_suffix('.sqlite3')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initial_queues = dict(initial_queues or {})
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS allocations (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT NOT NULL UNIQUE,
                    record TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS ledger_meta (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')
            db.execute('BEGIN IMMEDIATE')
            if not db.execute("SELECT 1 FROM ledger_meta WHERE key='version'").fetchone():
                db.execute("INSERT INTO ledger_meta VALUES ('version', ?)", (uuid.uuid4().hex,))
            if not db.execute("SELECT 1 FROM ledger_meta WHERE key='legacy_imported'").fetchone():
                if legacy.suffix == '.jsonl' and legacy.exists():
                    # Malformed data aborts the import; duplicate order_ids
                    # skip (keep the first) — one stray dupe in a demo
                    # ledger must not brick every future startup, and the
                    # flag below must be written either way.
                    seen, skipped = set(), []
                    for line in legacy.read_text(encoding='utf-8').splitlines():
                        if line.strip():
                            record = allocation_from_dict(json.loads(line))
                            if record.order_id in seen:
                                skipped.append(record.order_id)
                                continue
                            seen.add(record.order_id)
                            db.execute('INSERT INTO allocations(order_id, record) VALUES (?, ?)',
                                       (record.order_id, json.dumps(to_dict(record))))
                    if skipped:
                        print(f"legacy import: skipped duplicate order_ids {skipped}")
                db.execute("INSERT INTO ledger_meta VALUES ('legacy_imported', '1')")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=15)
        try:
            with db:
                db.execute('PRAGMA busy_timeout=15000')
                yield db
        finally:
            db.close()

    @staticmethod
    def _version(db):
        return db.execute("SELECT value FROM ledger_meta WHERE key='version'").fetchone()[0]

    @property
    def version(self):
        with self.connection() as db:
            return self._version(db)

    @staticmethod
    def _records(db):
        return [allocation_from_dict(json.loads(row[0])) for row in
                db.execute('SELECT record FROM allocations ORDER BY seq')]

    def load_all(self):
        with self.connection() as db:
            return self._records(db)

    def _queues(self, db):
        queues = dict(self.initial_queues)
        for rec in self._records(db):
            queues[rec.workshop_id] = (queues.get(rec.workshop_id, rec.queue_before)
                                       + rec.queue_after - rec.queue_before)
        return queues

    def queues(self):
        with self.connection() as db:
            return self._queues(db)

    def append(self, record):
        """Compatibility/import entry point; runtime commits use allocate()."""
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO allocations(order_id, record) VALUES (?, ?)',
                       (record.order_id, json.dumps(to_dict(record), ensure_ascii=False)))
            db.execute("UPDATE ledger_meta SET value=? WHERE key='version'", (uuid.uuid4().hex,))

    def allocate(self, order, workshop, *, committed_by, expected_version=None,
                 decision_id='', evidence=None):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT record FROM allocations WHERE order_id=?',
                                  (order['order_id'],)).fetchone()
            if existing:
                old = json.loads(existing[0])
                raise ValueError(f"{order['order_id']} was already committed to "
                                 f"{old['workshop_id']} ({old['record_id']}). Refusing the duplicate commit.")
            if expected_version is not None and expected_version != self._version(db):
                raise StaleAllocation('Queues changed. Review the updated proposal before confirming.')
            before = self._queues(db)[workshop.workshop_id]
            added = int(order['pieces']) / workshop.capacity * (1 + .5 * workshop.defect_rate)
            seq = db.execute("SELECT COALESCE((SELECT seq FROM sqlite_sequence WHERE name='allocations'), 0) + 1").fetchone()[0]
            record = AllocationRecord(
                record_id=f'A-{seq:04d}', decision_id=decision_id or order['order_id'],
                order_id=order['order_id'], workshop_id=workshop.workshop_id,
                pieces=int(order['pieces']), committed_by=committed_by,
                # world date + wall-clock time-of-day: the desk world sits at
                # CHAT_AS_OF, but same-day records stay ordered by the clock
                committed_at=f"{CHAT_AS_OF}T{datetime.now(timezone.utc):%H:%M:%S}+00:00",
                queue_before=before, queue_after=before + added,
                evidence=evidence or {})
            db.execute('INSERT INTO allocations(order_id, record) VALUES (?, ?)',
                       (record.order_id, json.dumps(to_dict(record), ensure_ascii=False)))
            db.execute("UPDATE ledger_meta SET value=? WHERE key='version'", (uuid.uuid4().hex,))
            return record

    def reset(self):
        """Reset demo allocations atomically, retaining API usage and old records."""
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS allocation_archive '
                       '(archived_at TEXT NOT NULL, record TEXT NOT NULL)')
            db.execute("INSERT INTO allocation_archive SELECT ?, record FROM allocations",
                       (datetime.now(timezone.utc).isoformat(),))
            db.execute('DELETE FROM allocations')
            db.execute("UPDATE ledger_meta SET value=? WHERE key='version'", (uuid.uuid4().hex,))
