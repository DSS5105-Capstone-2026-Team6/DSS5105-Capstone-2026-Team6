"""Measure interactive DB latency: fresh connection per op vs pooled.

Times N read round-trips against the configured shared database two ways:
  A) a brand-new psycopg connection per query (the pre-#40 behaviour)
  B) one pooled connection reused (the current behaviour)
Prints mean/median for both. Uses the same credentials as the app
(.env / environment); never prints them.

Run from the repository root:
    .venv/Scripts/python.exe scripts/bench_db_latency.py
"""
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

N = 8


def main():
    from desk.storage import database_setting
    url = database_setting("DISPATCH_DATABASE_URL")
    password = database_setting("DISPATCH_DATABASE_PASSWORD")
    if not url:
        raise SystemExit("Set DISPATCH_DATABASE_URL (+ _PASSWORD) in .env first.")
    import psycopg
    from psycopg_pool import ConnectionPool

    kw = {"password": password} if password else {}
    sql = "SELECT value FROM ledger_meta WHERE key='version'"

    # A: fresh connection per query
    fresh = []
    for _ in range(N):
        t0 = time.perf_counter()
        with psycopg.connect(url, connect_timeout=10, sslmode="require",
                             prepare_threshold=None, **kw) as c:
            c.execute(sql).fetchone()
        fresh.append(time.perf_counter() - t0)

    # B: pooled (first call pays pool warmup, measured separately)
    pool = ConnectionPool(url, min_size=1, max_size=2, open=False,
                          kwargs={"connect_timeout": 10, "sslmode": "require",
                                  "prepare_threshold": None, **kw})
    t0 = time.perf_counter()
    pool.open(wait=True, timeout=10)
    warmup = time.perf_counter() - t0
    pooled = []
    for _ in range(N):
        t0 = time.perf_counter()
        with pool.connection() as c:
            c.execute(sql).fetchone()
        pooled.append(time.perf_counter() - t0)
    pool.close()

    def stats(v):
        return f"mean {statistics.mean(v):.3f}s · median {statistics.median(v):.3f}s · min {min(v):.3f}s · max {max(v):.3f}s"

    print(f"n={N} per mode, one small query per iteration")
    print(f"A fresh connection per query : {stats(fresh)}")
    print(f"B pooled, warm pool          : {stats(pooled)}")
    print(f"   (one-time pool warmup: {warmup:.3f}s)")
    print(f"speedup (mean): {statistics.mean(fresh)/statistics.mean(pooled):.1f}x")


if __name__ == "__main__":
    main()
