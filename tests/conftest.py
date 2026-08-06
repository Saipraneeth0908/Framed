"""Test environment.

Points every role at the local Postgres from deploy/docker-compose.yml and
supplies the secrets the apps now refuse to boot without. Imported before any
app module, because require_secret() runs at import time on purpose.
"""

from __future__ import annotations

import os

LOCAL_PG = "postgres://{role}@localhost:5433/framedobsessions?sslmode=disable"

os.environ.setdefault("FLASK_SECRET_KEY", "test-secret-storefront")
os.environ.setdefault("ADMIN_SECRET_KEY", "test-secret-admin")
# A valid Fernet key: exactly 32 url-safe base64 bytes. Test-only.
os.environ.setdefault("ADMIN_TOTP_KEY", "dGVzdC10b3RwLWtleS0zMi1ieXRlcy1sb25nLXh4eHg=")
os.environ.setdefault("EVENT_SALT_SEED", "test-salt-seed")
os.environ.setdefault("REDIS_URL", "redis://localhost:6380/0")
os.environ.setdefault("FO_INSECURE_COOKIES", "1")          # test client speaks http
os.environ.setdefault("DATABASE_URL", LOCAL_PG.format(role="postgres:postgres"))
os.environ.setdefault("STORE_DATABASE_URL", LOCAL_PG.format(role="store_app:store_app_dev"))
os.environ.setdefault("ADMIN_DATABASE_URL", LOCAL_PG.format(role="admin_app:admin_app_dev"))
os.environ.setdefault("INGEST_DATABASE_URL", LOCAL_PG.format(role="ingest:ingest_dev"))
os.environ.setdefault("ETL_DATABASE_URL", LOCAL_PG.format(role="etl:etl_dev"))
os.environ.setdefault("DB_POOL_MAX", "4")

import pytest  # noqa: E402
from flask.testing import FlaskClient  # noqa: E402

from common.csrf import FIELD  # noqa: E402


class CsrfClient(FlaskClient):
    """Attaches the session CSRF token to form posts.

    Without this every existing test would have to learn about CSRF, which
    tells us nothing about the behaviour under test.
    """

    def open(self, *args, **kwargs):
        # Default a bare POST to an empty form dict so the token still lands.
        # A caller who passes data= as a raw string opts out on purpose -- that
        # is how test_csrf_is_required_on_every_mutating_form checks the guard.
        if kwargs.get("method", "").upper() == "POST" and "data" not in kwargs and "json" not in kwargs:
            kwargs["data"] = {}
        data = kwargs.get("data")
        if isinstance(data, dict) and FIELD not in data:
            with self.session_transaction() as sess:
                data[FIELD] = sess.setdefault(FIELD, "test-csrf-token")
        return super().open(*args, **kwargs)


RESET_SQL = """
-- Test-only: step around the two guards that exist precisely to stop this.
alter table store.order_items    disable trigger t_freeze_order_items;
alter table ops.inventory_ledger disable trigger t_ledger_append_only;

delete from ops.inventory_ledger where note is distinct from 'Opening balance (migration 008)';
delete from store.refunds;
delete from store.shipments;
delete from store.order_items;
delete from store.orders;
delete from store.cart_items;
delete from store.carts;
delete from store.customers;

-- Rebuild the cached balances from what is left of the ledger, so
-- ops.ledger_drift() is empty at the start of every run.
update ops.components c
   set on_hand  = coalesce(l.d, 0),
       reserved = coalesce(l.r, 0)
  from (select component_id, sum(delta) d, sum(reserved_delta) r
          from ops.inventory_ledger group by component_id) l
 where l.component_id = c.id;
update ops.components set on_hand = 0, reserved = 0
 where id not in (select component_id from ops.inventory_ledger);

alter table ops.inventory_ledger enable trigger t_ledger_append_only;
alter table store.order_items    enable trigger t_freeze_order_items;
"""


@pytest.fixture(scope="session", autouse=True)
def clean_slate():
    """Start every run from a known transactional state.

    Orders reserve real stock, so a suite that appends to the previous run
    eventually exhausts a component and the oversell guard -- correctly --
    starts refusing checkouts. Resetting is cheaper than re-migrating.
    """
    from urllib.parse import urlparse

    from db.conn import Role, tx

    host = (urlparse(os.environ["DATABASE_URL"]).hostname or "").lower()
    if host not in {"localhost", "127.0.0.1", "postgres", "::1"}:
        raise RuntimeError(
            f"refusing to reset a non-local database (host={host!r}). "
            "Point DATABASE_URL at the compose Postgres before running the tests."
        )
    with tx(Role.SUPER) as cur:
        cur.execute(RESET_SQL)


@pytest.fixture()
def client():
    from web.app import app

    app.config.update(TESTING=True)
    app.test_client_class = CsrfClient
    with app.test_client() as test_client:
        yield test_client


@pytest.fixture()
def db():
    """Superuser cursor factory for arranging fixtures directly in Postgres."""
    from db.conn import Role, tx

    return lambda: tx(Role.SUPER)


# --------------------------------------------------------------------------- #
# Admin fixtures
# --------------------------------------------------------------------------- #

ADMIN_PASSWORD = "correct-horse-battery-staple"


@pytest.fixture(scope="session")
def admin_app():
    from admin.app import app as flask_app

    flask_app.config.update(TESTING=True)
    flask_app.test_client_class = CsrfClient
    return flask_app


@pytest.fixture()
def staff(admin_app):
    """One account per role, created once and reused. Passwords are known."""
    from admin.auth import hash_password
    from db.conn import Role, tx

    people = {}
    with tx(Role.SUPER) as cur:
        for role in ("owner", "manager", "inventory", "fulfilment"):
            email = f"{role}@test.local"
            cur.execute(
                """insert into ops.users (email, name, password_hash, role)
                   values (%s, %s, %s, %s::admin_role)
                   on conflict (email) where archived_at is null
                     do update set password_hash = excluded.password_hash,
                                   role = excluded.role,
                                   failed_attempts = 0, locked_until = null
                returning id, session_version""",
                (email, role.capitalize(), hash_password(ADMIN_PASSWORD), role),
            )
            row = cur.fetchone()
            people[role] = {"id": row["id"], "email": email, "sv": row["session_version"]}
    return people


@pytest.fixture()
def scratch_product():
    """A draft product for mutation tests.

    Draft, so load_products() (which selects status='active') never sees it and
    tests/test_catalog_parity.py stays honest. Upserted on a fixed slug so runs
    do not accumulate rows.
    """
    from db.conn import Role, tx

    with tx(Role.SUPER) as cur:
        cur.execute(
            """insert into store.products (legacy_id, slug, name, category, status, position)
               values ('ptest', 'zz-test-scratch', 'Scratch product', 'hotwheels', 'draft', 999)
               on conflict (slug) where archived_at is null
                 do update set name = 'Scratch product', status = 'draft'
            returning id""",
        )
        return cur.fetchone()["id"]


@pytest.fixture()
def as_role(admin_app, staff):
    """Log a client in as a given role, bypassing the TOTP challenge.

    The TOTP flow has its own tests; every other admin test is about
    authorization, and re-deriving a one-time code in each of them would test
    pyotp rather than the routes.
    """
    from datetime import datetime, timezone

    def _login(role: str):
        client = admin_app.test_client()
        person = staff[role]
        with client.session_transaction() as sess:
            now = datetime.now(timezone.utc).timestamp()
            sess.update({"uid": person["id"], "sv": person["sv"],
                         "started_at": now, "seen_at": now})
        return client

    return _login
