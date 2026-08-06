"""Roles and permissions.

A static enum set, not a database-driven matrix with a management UI: there are
four roles and about thirty permissions, and nobody is asking for custom roles.
Promoting this to ops.role_permissions later is a migration, not a redesign.

Deny by default. A route with no @require decorator fails
tests/test_admin_rbac.py::test_every_admin_route_declares_a_permission.
"""

from __future__ import annotations

from enum import Enum
from functools import wraps

from flask import abort, g


class Perm(str, Enum):
    PRODUCT_VIEW = "product.view"
    PRODUCT_EDIT = "product.edit"
    PRICE_EDIT = "price.edit"

    STOCK_VIEW = "stock.view"
    STOCK_EDIT = "stock.edit"

    PRODUCTION_VIEW = "production.view"
    PRODUCTION_EDIT = "production.edit"

    ORDER_VIEW = "order.view"
    ORDER_EDIT = "order.edit"            # status, tracking, notes
    ORDER_REFUND = "order.refund"
    ORDER_CANCEL = "order.cancel"

    CUSTOMER_VIEW = "customer.view"      # full PII
    CUSTOMER_SHIP_VIEW = "customer.ship" # shipping address only
    CUSTOMER_EXPORT = "customer.export"

    DISCOUNT_EDIT = "discount.edit"

    ANALYTICS_VIEW = "analytics.view"

    SETTINGS_VIEW = "settings.view"
    SETTINGS_EDIT = "settings.edit"
    USER_MANAGE = "user.manage"
    AUDIT_VIEW = "audit.view"

    ARCHIVE = "record.archive"
    HARD_DELETE = "record.delete"


_ALL = frozenset(Perm)

# Mirrors the permission table in the architecture doc, one row per role.
ROLE_PERMS: dict[str, frozenset[Perm]] = {
    "owner": _ALL,
    "manager": _ALL - {Perm.USER_MANAGE, Perm.SETTINGS_EDIT, Perm.HARD_DELETE},
    "inventory": frozenset({
        Perm.PRODUCT_VIEW, Perm.PRODUCT_EDIT, Perm.PRICE_EDIT,
        Perm.STOCK_VIEW, Perm.STOCK_EDIT,
        Perm.PRODUCTION_VIEW,
        Perm.ORDER_VIEW,
        Perm.ARCHIVE,
    }),
    "fulfilment": frozenset({
        Perm.PRODUCT_VIEW,
        Perm.STOCK_VIEW,
        Perm.PRODUCTION_VIEW, Perm.PRODUCTION_EDIT,
        Perm.ORDER_VIEW, Perm.ORDER_EDIT,
        Perm.CUSTOMER_SHIP_VIEW,
    }),
}


def permissions_for(role: str) -> frozenset[Perm]:
    return ROLE_PERMS.get(role, frozenset())


def has(perm: Perm) -> bool:
    user = getattr(g, "user", None)
    return bool(user) and perm in permissions_for(user["role"])


def require(perm: Perm):
    """Guard a route. Checked server-side, before any work happens.

    Hiding a nav item is cosmetic; this is the control. The decorator also
    records the permission on the view function so CI can assert coverage.
    """

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not getattr(g, "user", None):
                abort(401)
            if not has(perm):
                abort(403)
            return view(*args, **kwargs)

        wrapped.__fo_permission__ = perm
        return wrapped

    return decorator


def public(view):
    """Explicit opt-out for login/logout/health. Never a silent omission."""
    view.__fo_permission__ = None
    view.__fo_public__ = True
    return view
