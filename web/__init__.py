"""Customer-facing storefront.

Runs as its own process on its own hostname with its own cookie and its own
database role (store_app). It has no admin routes and no way to reach the ops
schema -- see db/migrations/20260805000001_schemas_roles.sql.
"""
