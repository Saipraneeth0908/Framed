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
os.environ.setdefault("ADMIN_TOTP_KEY", "dGVzdC10b3RwLWtleS0zMi1ieXRlcy1sb25nISE=")
os.environ.setdefault("EVENT_SALT_SEED", "test-salt-seed")
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
        data = kwargs.get("data")
        if isinstance(data, dict) and FIELD not in data:
            with self.session_transaction() as sess:
                data[FIELD] = sess.setdefault(FIELD, "test-csrf-token")
        return super().open(*args, **kwargs)


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
