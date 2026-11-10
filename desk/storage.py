"""Small storage adapter: SQLite locally, PostgreSQL for a shared deployment.

All writers take the same transaction lock. This keeps duplicate checks,
queue-version checks and writes together even across web and bot processes.
"""
from contextlib import contextmanager
import os
import re
from pathlib import Path
import sqlite3

from .config import PROJECT_ROOT, RESULTS_DIR


def database_setting(name):
    """Read credentials locally or from Streamlit Secrets; never print them."""
    if not os.environ.get(name):
        try:
            from dotenv import load_dotenv
            load_dotenv(PROJECT_ROOT / ".env", override=False)
        except ImportError:
            pass
    value = os.environ.get(name, "").strip()
    if not value:
        try:
            import streamlit as st
            value = str(st.secrets.get(name, "")).strip()
        except Exception:
            pass
    return value


def database_url():
    return database_setting("DISPATCH_DATABASE_URL")


class _PostgresConnection:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, parameters=()):
        # These are application-owned statements, never user-supplied SQL.
        if sql == "BEGIN IMMEDIATE":
            return self.connection.execute("SELECT pg_advisory_xact_lock(5105, 1)")
        return self.connection.execute(sql.replace("%", "%%").replace("?", "%s"), parameters)


class Database:
    def __init__(self, path=None, *, url=None):
        # Explicit paths keep offline tests/local experiments isolated.
        self._url = (database_url() if path is None else "") if url is None else url
        self.is_postgres = bool(self._url)
        if self.is_postgres:
            if not self._url.startswith(("postgresql://", "postgres://")):
                raise ValueError("DISPATCH_DATABASE_URL must be a PostgreSQL connection URI.")
            self.path = None
            self._password = database_setting("DISPATCH_DATABASE_PASSWORD")
            self.schema = os.environ.get("DISPATCH_DATABASE_SCHEMA", "public")
            if not re.fullmatch(r"[a-z][a-z0-9_]*", self.schema):
                raise ValueError("Invalid database schema name.")
        else:
            self.path = Path(path or os.environ.get("DISPATCH_DB_PATH")
                             or RESULTS_DIR / "audit_log.sqlite3")
            self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self):
        if self.is_postgres:
            try:
                import psycopg
            except ImportError:
                raise RuntimeError("Install psycopg[binary] to use the shared database.") from None
            try:
                kwargs = {"password": self._password} if self._password else {}
                connection = psycopg.connect(
                    self._url, connect_timeout=10, sslmode="require",
                    prepare_threshold=None, **kwargs)
            except psycopg.Error:
                raise RuntimeError(
                    "Cannot connect to the shared database. Check the connection URI, "
                    "database password, network and Supabase project status.") from None
            with connection:
                # SET LOCAL belongs to this transaction, including on poolers.
                connection.execute("SET LOCAL search_path TO " + self.schema)
                yield _PostgresConnection(connection)
        else:
            connection = sqlite3.connect(self.path, timeout=15)
            try:
                with connection:
                    connection.execute("PRAGMA busy_timeout=15000")
                    yield connection
            finally:
                connection.close()

    def require_tables(self, *names):
        if not self.is_postgres:
            return
        with self.connect() as db:
            for name in names:
                if db.execute("SELECT to_regclass(?)", (self.schema + "." + name,)).fetchone()[0] is None:
                    raise RuntimeError("Shared database tables are missing. Run database/supabase_schema.sql first.")
