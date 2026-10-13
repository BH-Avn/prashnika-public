"""Database connections for the public site, kept open and reused.

Opening a Postgres connection costs ~10-15 ms (TCP + password check), and /api/filters runs about ten small
queries, so a fresh connection per query made it ~150 ms. connect() here hands out a pooled connection whose
close() puts it back instead of closing it. The site only reads, so connections are autocommit: every query sees
the latest committed data and none sits idle inside a transaction.

JIT is off for them: Postgres compiles a query to machine code once its cost estimate looks big (the question list's
does), which took 10-40 ms on every such query here and never paid off on tables this small.
"""

import threading

import psycopg2
import psycopg2.extras
from psycopg2 import pool

from qh.db import DSN

MAX = 8                                             # uvicorn runs sync endpoints on up to 40 threads; more than
                                                    # MAX at once just get a plain connection of their own
OPTIONS = "-c jit=off"
_pool = None
_lock = threading.Lock()


def fresh():
    """A plain (unpooled) connection with the site's settings."""
    return psycopg2.connect(DSN, cursor_factory=psycopg2.extras.RealDictCursor, options=OPTIONS)


class _Pooled:
    """A pooled connection: the same cursor()/close() as a psycopg2 connection, but close() returns it."""

    def __init__(self, conn):
        self._conn = conn

    def cursor(self, *a, **kw):
        return self._conn.cursor(*a, **kw)

    def close(self):
        conn, self._conn = self._conn, None
        if conn is None:
            return
        bad = conn.closed or conn.get_transaction_status() not in (psycopg2.extensions.TRANSACTION_STATUS_IDLE,)
        _pool.putconn(conn, close=bool(bad))

    def __getattr__(self, name):
        return getattr(self._conn, name)


def _get_pool():
    global _pool
    with _lock:
        if _pool is None:
            # minconn = MAX: psycopg2's pool closes a returned connection once it holds minconn idle ones, so a
            # lower minimum would quietly go back to one connection per query
            _pool = pool.ThreadedConnectionPool(MAX, MAX, DSN, cursor_factory=psycopg2.extras.RealDictCursor,
                                           options=OPTIONS)
        return _pool


def connect():
    p = _get_pool()
    try:
        conn = p.getconn()
    except pool.PoolError:                          # all in use: a one-off connection
        conn = fresh()
        conn.autocommit = True
        return conn
    try:                                            # a connection the server dropped (restart, timeout) is replaced
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
    except psycopg2.Error:
        p.putconn(conn, close=True)
        conn = p.getconn()
        conn.autocommit = True
    return _Pooled(conn)
