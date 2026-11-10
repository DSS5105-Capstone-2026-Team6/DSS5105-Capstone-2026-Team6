"""Read-only connection check. Never prints the connection URI or password."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desk.storage import Database, database_setting, database_url


def main():
    if not database_url():
        print('Not configured: fill in the local .env database settings first.')
        return 1
    if database_setting('DISPATCH_DATABASE_PASSWORD') == 'REPLACE_WITH_YOUR_DATABASE_PASSWORD':
        print('Password not configured: replace the placeholder in .env and save.')
        return 1
    db = Database()
    tables = ('allocations', 'ledger_meta', 'performance', 'api_usage', 'allocation_archive')
    try:
        db.require_tables(*tables)
        with db.connect() as connection:
            for table in tables:
                count = connection.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                print(f'{table}: {count} rows')
    except Exception:
        print('Connection check failed. Check project status, credentials, network and schema.')
        return 1
    print('PASS: connected to PostgreSQL; all five tables are readable. No data was changed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
