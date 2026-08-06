"""Connection pools keyed by database role.

The role a process connects as *is* the isolation boundary (see migration 001):
web/ holds only store_app, admin/ only admin_app, collector/ only ingest. A
process cannot reach a schema its role was not granted, whatever its code does.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


class Role:
    STORE = "STORE"
    ADMIN = "ADMIN"
    INGEST = "INGEST"
    ETL = "ETL"
    SUPER = ""          # DATABASE_URL -- migrations, seeds and tests only


_pools: dict[str, ConnectionPool] = {}

_FALLBACK = "postgres://postgres:postgres@localhost:5433/framedobsessions?sslmode=disable"


def _url(role: str) -> str:
    var = f"{role}_DATABASE_URL" if role else "DATABASE_URL"
    url = os.environ.get(var) or os.environ.get("DATABASE_URL")
    if not url:
        # Dev convenience only: deploy/docker-compose.yml maps Postgres to 5433.
        # Every container in deploy/ gets an explicit URL, so this never fires
        # in a deployed process.
        url = _FALLBACK
    return url


def pool(role: str = Role.STORE) -> ConnectionPool:
    if role not in _pools:
        _pools[role] = ConnectionPool(
            _url(role),
            min_size=int(os.environ.get("DB_POOL_MIN", "1")),
            max_size=int(os.environ.get("DB_POOL_MAX", "8")),
            kwargs={"row_factory": dict_row, "application_name": f"fo_{role.lower() or 'super'}"},
            open=True,
            timeout=float(os.environ.get("DB_POOL_TIMEOUT", "10")),
        )
    return _pools[role]


@contextmanager
def tx(role: str = Role.STORE, actor_id: int | None = None, request_id: str | None = None) -> Iterator[Any]:
    """One transaction, one cursor.

    ``actor_id``/``request_id`` are pushed into transaction-local GUCs so the
    generic audit trigger can stamp every mutation without the caller writing a
    single log line. Forgetting the actor degrades to a NULL actor on a row that
    still exists -- it cannot suppress the row.
    """
    with pool(role).connection() as conn:
        with conn.cursor() as cur:
            if actor_id is not None:
                cur.execute("select set_config('app.actor_id', %s, true)", (str(actor_id),))
            if request_id:
                cur.execute("select set_config('app.request_id', %s, true)", (request_id,))
            yield cur


def fetch_all(sql: str, params: tuple | dict | None = None, *, role: str = Role.STORE) -> list[dict]:
    with tx(role) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def fetch_one(sql: str, params: tuple | dict | None = None, *, role: str = Role.STORE) -> dict | None:
    with tx(role) as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def execute(sql: str, params: tuple | dict | None = None, *, role: str = Role.STORE,
            actor_id: int | None = None) -> int:
    with tx(role, actor_id=actor_id) as cur:
        cur.execute(sql, params)
        return cur.rowcount


def close_all() -> None:
    for p in _pools.values():
        p.close()
    _pools.clear()
