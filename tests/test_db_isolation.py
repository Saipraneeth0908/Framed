"""The isolation model, checked rather than asserted in prose."""

from __future__ import annotations

import os

import pytest
from psycopg import errors

from db.conn import Role, _url, tx


def test_a_missing_role_url_refuses_rather_than_using_the_superuser(monkeypatch):
    """The most dangerous possible default.

    Falling back to DATABASE_URL would give the storefront superuser access and
    silently undo every grant in migration 001 -- while appearing to work.
    """
    monkeypatch.delenv("STORE_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgres://postgres:postgres@localhost:5433/framedobsessions")
    with pytest.raises(RuntimeError, match="STORE_DATABASE_URL is not set"):
        _url(Role.STORE)


def test_each_role_url_names_the_role_it_claims():
    for role, expected in (
        (Role.STORE, "store_app"), (Role.ADMIN, "admin_app"), (Role.ETL, "etl"),
    ):
        assert expected in _url(role), f"{role} is not connecting as {expected}"


def test_each_process_connects_as_its_own_role():
    for role, expected in ((Role.STORE, "store_app"), (Role.ADMIN, "admin_app"), (Role.ETL, "etl")):
        with tx(role) as cur:
            cur.execute("select current_user as who")
            assert cur.fetchone()["who"] == expected


@pytest.mark.parametrize("table", ["ops.users", "ops.audit_log", "ops.settings"])
def test_the_storefront_cannot_read_admin_tables(table):
    with pytest.raises(errors.InsufficientPrivilege):
        with tx(Role.STORE) as cur:
            cur.execute(f"select * from {table} limit 1")


def test_the_storefront_cannot_change_an_order_total():
    """It can insert an order and settle payment; it cannot rewrite the money."""
    with pytest.raises(errors.InsufficientPrivilege):
        with tx(Role.STORE) as cur:
            cur.execute("update store.orders set total_cents = 1 where id > 0")


def test_the_storefront_cannot_edit_the_catalog():
    with pytest.raises(errors.InsufficientPrivilege):
        with tx(Role.STORE) as cur:
            cur.execute("update store.variants set price_cents = 1 where id > 0")


def test_bi_reader_sees_marts_and_nothing_else():
    os.environ.setdefault(
        "BI_DATABASE_URL",
        "postgres://bi_reader:bi_reader_dev@localhost:5433/framedobsessions?sslmode=disable",
    )
    from db.conn import pool

    with pool("BI").connection() as conn, conn.cursor() as cur:
        cur.execute("select has_schema_privilege('bi_reader', 'mart', 'USAGE') as ok")
        assert cur.fetchone()["ok"] is True
        for schema in ("store", "ops", "raw"):
            cur.execute("select has_schema_privilege('bi_reader', %s, 'USAGE') as ok", (schema,))
            assert cur.fetchone()["ok"] is False, f"bi_reader can reach {schema}"


def test_bi_reader_is_read_only():
    from db.conn import pool

    with pool("BI").connection() as conn, conn.cursor() as cur:
        cur.execute("show default_transaction_read_only")
        assert cur.fetchone()["default_transaction_read_only"] == "on"
