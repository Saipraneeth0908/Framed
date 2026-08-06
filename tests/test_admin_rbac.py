"""Sprint 2 acceptance.

Unauthenticated and wrong-role requests to every route are refused, and audit
rows appear without any application-level logging call.
"""

from __future__ import annotations

import pytest

from admin.rbac import ROLE_PERMS, Perm, permissions_for
from db.conn import Role, tx

# Routes that legitimately carry no permission, each for a stated reason.
#   auth.*   -- you cannot require a session to create one
#   healthz  -- the orchestrator has no credentials
#   readyz   -- same, and it must answer while the database is down
#   static   -- CSS
#   prometheus_metrics -- Prometheus cannot log in. It exposes route names and
#       latencies, never records, and deploy/Caddyfile refuses it from the
#       internet so only the scrape network reaches it.
PUBLIC_ENDPOINTS = {
    "auth.login", "auth.totp_challenge", "auth.enroll", "auth.logout", "auth.change_password",
    "healthz", "readyz", "static", "prometheus_metrics",
}


def _admin_rules(admin_app):
    for rule in admin_app.url_map.iter_rules():
        if rule.endpoint in PUBLIC_ENDPOINTS:
            continue
        yield rule


def test_every_admin_route_declares_a_permission(admin_app):
    """Deny by default: a new route without @require fails the build."""
    undeclared = [
        rule.endpoint
        for rule in _admin_rules(admin_app)
        if not hasattr(admin_app.view_functions[rule.endpoint], "__fo_permission__")
    ]
    assert undeclared == [], (
        f"these routes have no @require(...) or @public: {undeclared}. "
        "Add one -- an undecorated admin route is an open door."
    )


def test_unauthenticated_requests_are_redirected_to_login(admin_app):
    client = admin_app.test_client()
    for rule in _admin_rules(admin_app):
        if "GET" not in rule.methods or rule.arguments:
            continue
        response = client.get(rule.rule)
        assert response.status_code in (302, 401), f"{rule.rule} served without a session"
        if response.status_code == 302:
            assert "/login" in response.headers["Location"]


@pytest.mark.parametrize("path", ["/", "/orders/", "/inventory/", "/system/audit"])
def test_owner_reaches_everything(as_role, path):
    assert as_role("owner").get(path).status_code == 200


def test_fulfilment_cannot_see_staff_or_settings_edit(as_role):
    client = as_role("fulfilment")
    assert client.get("/people/users").status_code == 403
    assert client.get("/people/customers").status_code == 403
    assert client.get("/system/audit").status_code == 403


def test_fulfilment_can_work_the_production_board(as_role):
    assert as_role("fulfilment").get("/production/").status_code == 200


def test_inventory_role_cannot_refund(as_role):
    response = as_role("inventory").post("/orders/1/refund", data={"amount": "10.00", "reason": "x"})
    assert response.status_code == 403


def test_manager_cannot_manage_staff_or_hard_delete():
    manager = permissions_for("manager")
    assert Perm.USER_MANAGE not in manager
    assert Perm.HARD_DELETE not in manager
    assert Perm.ORDER_REFUND in manager


def test_owner_holds_every_permission():
    assert ROLE_PERMS["owner"] == frozenset(Perm)


def test_no_role_except_owner_can_hard_delete():
    for role, perms in ROLE_PERMS.items():
        if role != "owner":
            assert Perm.HARD_DELETE not in perms


def test_nav_hiding_is_not_the_control(as_role):
    """A hidden nav item is cosmetic; the server must refuse regardless."""
    body = as_role("fulfilment").get("/").data
    assert b"/people/users" not in body
    assert as_role("fulfilment").post("/people/users", data={"email": "x@y.z"}).status_code == 403


def test_audit_rows_are_written_without_any_application_logging(as_role, staff, scratch_product):
    """No admin view calls an audit function. The trigger does it anyway."""
    product_id = scratch_product
    with tx(Role.SUPER) as cur:
        cur.execute("select count(*) as n from ops.audit_log where entity = 'store.products'")
        before = cur.fetchone()["n"]

    response = as_role("owner").post(
        f"/catalog/{product_id}",
        data={"name": "Audited rename", "category": "hotwheels", "status": "draft", "position": "999"},
    )
    assert response.status_code == 302

    with tx(Role.SUPER) as cur:
        cur.execute(
            """select actor_id, action, before, after from ops.audit_log
                where entity = 'store.products' and entity_id = %s
                order by id desc limit 1""",
            (product_id,),
        )
        entry = cur.fetchone()
        cur.execute("select count(*) as n from ops.audit_log where entity = 'store.products'")
        after = cur.fetchone()["n"]

    assert after > before
    assert entry["action"] == "update"
    assert entry["actor_id"] == staff["owner"]["id"], "the actor GUC did not reach the trigger"
    assert entry["after"]["name"] == "Audited rename"


def test_session_version_bump_kills_live_sessions(as_role, staff):
    client = as_role("manager")
    assert client.get("/").status_code == 200
    with tx(Role.SUPER) as cur:
        cur.execute("update ops.users set session_version = session_version + 1 where id = %s",
                    (staff["manager"]["id"],))
    response = client.get("/")
    assert response.status_code == 302 and "/login" in response.headers["Location"]


def test_storefront_role_cannot_read_admin_tables():
    """The isolation claim, checked rather than asserted in prose."""
    from psycopg import errors

    with pytest.raises(errors.InsufficientPrivilege):
        with tx(Role.STORE) as cur:
            cur.execute("select * from ops.users limit 1")


def test_storefront_role_cannot_read_the_audit_log():
    from psycopg import errors

    with pytest.raises(errors.InsufficientPrivilege):
        with tx(Role.STORE) as cur:
            cur.execute("select * from ops.audit_log limit 1")
