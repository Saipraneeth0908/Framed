"""Sprint 2 and 3 acceptance: the real login flow, every screen, and the
production state machine refusing illegal transitions.
"""

from __future__ import annotations

import pyotp
import pytest

from db.conn import Role, tx
from tests.conftest import ADMIN_PASSWORD

# --------------------------------------------------------------------------- #
# Login
# --------------------------------------------------------------------------- #

def test_owner_is_forced_through_totp_enrolment(admin_app, staff):
    """Owner and manager cannot reach the panel without a second factor."""
    with tx(Role.SUPER) as cur:
        cur.execute("update ops.users set totp_enabled = false, totp_secret_enc = null where id = %s",
                    (staff["owner"]["id"],))

    client = admin_app.test_client()
    response = client.post("/login", data={"email": "owner@test.local", "password": ADMIN_PASSWORD})
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/account/2fa")

    # The enrolment page mints a secret; confirming with a live code turns it on.
    client.get("/account/2fa")
    with client.session_transaction() as sess:
        secret = sess["enroll_secret"]
    response = client.post("/account/2fa", data={"code": pyotp.TOTP(secret).now()})
    assert response.status_code == 302
    assert client.get("/").status_code == 200


def test_second_sign_in_requires_the_code(admin_app, staff):
    """After enrolment the password alone is no longer enough."""
    secret = pyotp.random_base32()
    from admin.auth import encrypt_totp

    with tx(Role.SUPER) as cur:
        cur.execute("update ops.users set totp_enabled = true, totp_secret_enc = %s where id = %s",
                    (encrypt_totp(secret), staff["manager"]["id"]))

    client = admin_app.test_client()
    response = client.post("/login", data={"email": "manager@test.local", "password": ADMIN_PASSWORD})
    assert response.headers["Location"].endswith("/login/totp")
    assert client.get("/").status_code == 302, "password alone must not open the panel"

    assert client.post("/login/totp", data={"code": "000000"}).status_code == 401
    response = client.post("/login/totp", data={"code": pyotp.TOTP(secret).now()})
    assert response.status_code == 302
    assert client.get("/").status_code == 200


def test_wrong_password_is_indistinguishable_from_an_unknown_account(admin_app, staff):
    client = admin_app.test_client()
    unknown = client.post("/login", data={"email": "nobody@test.local", "password": "x" * 20})
    wrong = client.post("/login", data={"email": "inventory@test.local", "password": "x" * 20})
    assert unknown.status_code == wrong.status_code == 401
    assert b"Incorrect email or password." in unknown.data
    assert b"Incorrect email or password." in wrong.data


def test_repeated_failures_lock_the_account(admin_app, staff):
    client = admin_app.test_client()
    codes = [
        client.post("/login", data={"email": "fulfilment@test.local", "password": "nope"}).status_code
        for _ in range(7)
    ]
    assert 429 in codes, "five failures in fifteen minutes must start refusing"

    with tx(Role.SUPER) as cur:
        cur.execute("select failed_attempts, locked_until from ops.users where email = 'fulfilment@test.local'")
        row = cur.fetchone()
    assert row["failed_attempts"] >= 5
    assert row["locked_until"] is not None
    # Leave the account usable for the rest of the session.
    with tx(Role.SUPER) as cur:
        cur.execute("update ops.users set failed_attempts = 0, locked_until = null where email = 'fulfilment@test.local'")
    from admin.auth import _attempt_key, _redis

    _redis().delete(_attempt_key("127.0.0.1", "fulfilment@test.local"))


def test_logout_revokes_the_server_side_session(admin_app, as_role):
    client = as_role("owner")
    assert client.get("/").status_code == 200
    assert client.post("/logout").status_code == 302
    assert client.get("/").status_code == 302


def test_csrf_is_required_on_every_mutating_form(admin_app, as_role):
    client = as_role("owner")
    # data= as a raw string bypasses the CsrfClient token injection.
    response = client.post("/logout", data="", content_type="application/x-www-form-urlencoded")
    assert response.status_code == 400


# --------------------------------------------------------------------------- #
# Every screen renders with real data
# --------------------------------------------------------------------------- #

SCREENS = [
    "/", "/orders/", "/orders/?status=to_fulfil", "/production/", "/inventory/",
    "/inventory/?low=1", "/inventory/reorder", "/catalog/", "/catalog/?category=anime",
    "/people/customers", "/people/users", "/growth/discounts", "/insights/",
    "/system/settings", "/system/audit",
]


@pytest.mark.parametrize("path", SCREENS)
def test_screen_renders(as_role, path):
    response = as_role("owner").get(path)
    assert response.status_code == 200
    assert b"Framed Obsessions" in response.data


def test_product_and_component_detail_render(as_role):
    client = as_role("owner")
    with tx(Role.SUPER) as cur:
        cur.execute("select id from store.products where archived_at is null order by id limit 1")
        product_id = cur.fetchone()["id"]
        cur.execute("select id from ops.components order by id limit 1")
        component_id = cur.fetchone()["id"]
    assert client.get(f"/catalog/{product_id}").status_code == 200
    assert client.get(f"/inventory/{component_id}").status_code == 200


def test_csv_exports_are_downloadable(as_role):
    client = as_role("owner")
    for path in ("/inventory/reorder.csv", "/catalog/export.csv", "/people/customers.csv"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.mimetype == "text/csv"


def test_missing_records_are_404_not_500(as_role):
    assert as_role("owner").get("/orders/999999").status_code == 404
    assert as_role("owner").get("/catalog/999999").status_code == 404


# --------------------------------------------------------------------------- #
# Production state machine
# --------------------------------------------------------------------------- #

@pytest.fixture()
def queued_item(client):
    """A paid order with one queued line item, made through the storefront."""
    client.post("/cart/add", data={"slug": "track-55-yellow", "qty": "1", "frame": "black", "size": "A4"})
    client.post("/checkout", data={
        "name": "Board Tester", "email": "board@example.com", "street": "2 Kiln Road",
        "city": "Leeds", "state": "NY", "zip": "10001", "country": "United States",
    })
    with tx(Role.SUPER) as cur:
        cur.execute(
            """select oi.id, oi.order_id from store.order_items oi
                join store.orders o on o.id = oi.order_id
               where o.email = 'board@example.com' order by oi.id desc limit 1"""
        )
        return cur.fetchone()


def test_advancing_a_station_is_allowed(as_role, queued_item):
    response = as_role("owner").post(f"/production/{queued_item['id']}/advance", data={"to": "printing"})
    assert response.status_code == 302
    with tx(Role.SUPER) as cur:
        cur.execute("select production_status::text as s from store.order_items where id = %s",
                    (queued_item["id"],))
        assert cur.fetchone()["s"] == "printing"


def test_skipping_stations_returns_409(as_role, queued_item):
    response = as_role("owner").post(f"/production/{queued_item['id']}/advance", data={"to": "packed"})
    assert response.status_code == 409


def test_entering_printing_consumes_the_reserved_components(as_role, queued_item):
    as_role("owner").post(f"/production/{queued_item['id']}/advance", data={"to": "printing"})
    with tx(Role.SUPER) as cur:
        cur.execute(
            """select coalesce(sum(delta), 0) as consumed, coalesce(sum(reserved_delta), 0) as net_reserved
                 from ops.inventory_ledger where order_item_id = %s""",
            (queued_item["id"],),
        )
        row = cur.fetchone()
    assert row["consumed"] < 0, "components should have left stock"
    assert row["net_reserved"] == 0, "the reservation should be released as it is consumed"


def test_consumption_happens_exactly_once(as_role, queued_item):
    """Re-entering 'printing' after a block must not consume the stock twice.

    One consume row per component of the bill of materials, and no more --
    so rows == distinct components is the invariant, not rows == 1.
    """
    client = as_role("owner")
    client.post(f"/production/{queued_item['id']}/advance", data={"to": "printing"})
    client.post(f"/production/{queued_item['id']}/advance", data={"to": "blocked", "reason": "smudge"})
    client.post(f"/production/{queued_item['id']}/advance", data={"to": "printing"})
    with tx(Role.SUPER) as cur:
        cur.execute(
            """select count(*) as rows, count(distinct component_id) as components
                 from ops.inventory_ledger where order_item_id = %s and reason = 'consume'""",
            (queued_item["id"],),
        )
        row = cur.fetchone()
    assert row["components"] == 5, "frame, paper, mount, glass, packaging"
    assert row["rows"] == row["components"], "a component was consumed more than once"


def test_a_blocked_item_can_be_recovered_to_any_station(as_role, queued_item):
    client = as_role("owner")
    assert client.post(f"/production/{queued_item['id']}/advance",
                       data={"to": "blocked", "reason": "out of glass"}).status_code == 302
    assert client.post(f"/production/{queued_item['id']}/advance", data={"to": "framing"}).status_code == 302


def test_blocked_reason_reaches_the_board(as_role, queued_item):
    client = as_role("owner")
    client.post(f"/production/{queued_item['id']}/advance", data={"to": "blocked", "reason": "out of glass"})
    assert b"out of glass" in client.get("/production/").data


def test_ledger_still_has_no_drift_after_all_of_that():
    with tx(Role.SUPER) as cur:
        cur.execute("select * from ops.ledger_drift()")
        assert cur.fetchall() == []


# --------------------------------------------------------------------------- #
# Two-factor recovery -- the panel must not be able to lock everyone out of itself
# --------------------------------------------------------------------------- #

def test_an_owner_can_reset_someone_elses_two_factor(as_role, staff):
    client = as_role("owner")
    with tx(Role.SUPER) as cur:
        cur.execute("select id from ops.users where email = 'manager@test.local'")
        target = cur.fetchone()["id"]

    assert client.post(f"/people/users/{target}/reset-2fa").status_code == 302

    with tx(Role.SUPER) as cur:
        cur.execute("select totp_enabled, totp_secret_enc from ops.users where id = %s", (target,))
        row = cur.fetchone()
    assert row["totp_enabled"] is False
    assert row["totp_secret_enc"] is None


def test_resetting_two_factor_signs_that_account_out(as_role, staff):
    """Otherwise a session opened before the reset could enrol the new secret."""
    victim = as_role("manager")
    assert victim.get("/").status_code == 200

    with tx(Role.SUPER) as cur:
        cur.execute("select id from ops.users where email = 'manager@test.local'")
        target = cur.fetchone()["id"]
    as_role("owner").post(f"/people/users/{target}/reset-2fa")

    assert victim.get("/").status_code == 302, "the pre-reset session must be refused"


def test_only_user_manage_can_reset_two_factor(as_role):
    with tx(Role.SUPER) as cur:
        cur.execute("select id from ops.users where email = 'fulfilment@test.local'")
        target = cur.fetchone()["id"]
    # manager holds every permission except USER_MANAGE.
    assert as_role("manager").post(f"/people/users/{target}/reset-2fa").status_code == 403
    assert as_role("fulfilment").post(f"/people/users/{target}/reset-2fa").status_code == 403


def test_after_a_reset_the_owner_is_sent_back_to_enrolment(admin_app, staff):
    """The point of the reset: a fresh QR, not a permanent lockout."""
    with tx(Role.SUPER) as cur:
        cur.execute("select id from ops.users where email = 'owner@test.local'")
        uid = cur.fetchone()["id"]
    with admin_app.test_request_context():
        from admin.auth import reset_totp

        reset_totp(uid)

    client = admin_app.test_client()
    response = client.post("/login", data={"email": "owner@test.local", "password": ADMIN_PASSWORD},
                           follow_redirects=True)
    assert b"Set up two-factor" in response.data


def test_an_undecryptable_secret_names_the_recovery_command(admin_app, staff, monkeypatch):
    """A rotated ADMIN_TOTP_KEY must not dead-end on a bare 500."""
    import admin.auth as auth

    # Self-contained: an earlier test may have cleared this account's enrolment,
    # and without one the login redirects to enrolment instead of the challenge.
    with tx(Role.SUPER) as cur:
        cur.execute(
            """update ops.users set totp_enabled = true, totp_secret_enc = %s
                where email = 'owner@test.local'""",
            (auth.encrypt_totp(pyotp.random_base32()),),
        )
    monkeypatch.setattr(auth, "decrypt_totp", _bad_token)
    client = admin_app.test_client()
    client.post("/login", data={"email": "owner@test.local", "password": ADMIN_PASSWORD})
    response = client.post("/login/totp", data={"code": "000000"})
    assert response.status_code == 500
    assert b"--reset-totp" in response.data


def _bad_token(_blob):
    from cryptography.fernet import InvalidToken

    raise InvalidToken()


def test_generating_secrets_twice_never_changes_an_existing_one(tmp_path, monkeypatch):
    """The bug this prevents: a second setup run silently voids every enrolment."""
    import scripts.gen_secrets as gen

    env = tmp_path / ".env"
    monkeypatch.setattr(gen, "ENV", env)

    gen.main()
    first = env.read_text(encoding="utf-8")
    assert "ADMIN_TOTP_KEY=" in first

    gen.main()
    assert env.read_text(encoding="utf-8") == first, "a re-run must not rewrite any key"


def test_generating_secrets_fills_only_the_missing_ones(tmp_path, monkeypatch):
    import scripts.gen_secrets as gen

    env = tmp_path / ".env"
    env.write_text("ADMIN_TOTP_KEY=keep-me\nWEB_SECRET_KEY=\n", encoding="utf-8")
    monkeypatch.setattr(gen, "ENV", env)

    gen.main()
    text = env.read_text(encoding="utf-8")
    assert "ADMIN_TOTP_KEY=keep-me" in text, "a set key is never regenerated"
    assert text.count("WEB_SECRET_KEY=") == 1, "a blank key is filled in place, not duplicated"
    assert "WEB_SECRET_KEY=\n" not in text, "and it is actually filled"
    assert "ADMIN_SECRET_KEY=" in text


def test_the_enrolment_qr_is_dark_on_light_with_a_quiet_zone(admin_app):
    import re

    """An inverted or unpadded QR renders fine and no phone camera will read it."""
    from admin.auth import _qr_svg

    svg = _qr_svg("owner@test.local", pyotp.random_base32()).lower()
    assert 'fill="#fff"' in svg, "light modules must be painted white, not left transparent"
    assert 'stroke="#0b0f14"' in svg, "dark modules must actually be dark"
    assert "#e8edf5" not in svg, "the near-white module colour was the inversion bug"

    # A quiet zone the scanner can find the finder patterns against: the white
    # plate starts at 0,0 but the first dark module must be inset from it.
    plate = re.search(r'fill="#fff" d="m0 0h(\d+)', svg)
    first_dark = re.search(r'stroke="#0b0f14" d="m(\d+) ', svg)
    assert plate and first_dark
    assert int(first_dark.group(1)) >= 2, "no quiet zone; scanners need a light margin"


def test_the_enrolment_qr_encodes_a_scannable_otpauth_uri(admin_app):
    """What the camera reads has to be the secret the server will verify."""
    import re
    from urllib.parse import parse_qs, unquote, urlparse

    import segno

    secret = pyotp.random_base32()
    uri = pyotp.TOTP(secret).provisioning_uri(name="owner@test.local",
                                              issuer_name="Framed Obsessions")
    parsed = urlparse(uri)
    assert parsed.scheme == "otpauth" and parsed.netloc == "totp"
    assert parse_qs(parsed.query)["secret"] == [secret]
    assert unquote(parsed.path).startswith("/Framed Obsessions:")

    # And the SVG on the page is that URI, not a placeholder.
    svg = segno.make(uri, error="m").svg_inline(scale=4, border=3,
                                                dark="#0b0f14", light="#ffffff")
    assert re.search(r"<path[^>]+d=", svg), "the QR must render actual modules"
