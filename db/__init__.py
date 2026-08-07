"""Database access layer.

Plain SQL over psycopg 3, one connection pool per database role. No ORM: SQL is
the shared language across the Flask apps, dbt and Metabase, and the admin
queries are aggregate-heavy where an ORM fights you.

Escape hatch (from the architecture doc): if CRUD boilerplate passes ~1,500
lines, add SQLAlchemy Core for query building -- not the ORM.
"""

from db.conn import Role, close_all, execute, fetch_all, fetch_one, pool, tx

__all__ = ["fetch_all", "fetch_one", "execute", "tx", "pool", "close_all", "Role"]
