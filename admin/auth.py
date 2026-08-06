"""Identity: password hashing, TOTP, rate limiting, login and logout.

Argon2id rather than PBKDF2 -- memory-hard, and the winner of the competition
held to answer exactly this question. TOTP is mandatory for owner and manager;
those roles can refund money and change permissions.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

import pyotp
import redis
import segno
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken
from flask import (
    Blueprint,
    abort,
    current_app,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from admin.rbac import public
from db.conn import Role, tx

log = logging.getLogger(__name__)

hasher = PasswordHasher()
bp = Blueprint("auth", __name__)

MAX_ATTEMPTS = 5
ATTEMPT_WINDOW = timedelta(minutes=15)
TOTP_REQUIRED_ROLES = {"owner", "manager"}
IDLE_SECONDS = 30 * 60
ABSOLUTE_SECONDS = 12 * 60 * 60


def _redis():
    return redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6380/0"))


def _fernet() -> Fernet:
    key = os.environ.get("ADMIN_TOTP_KEY")
    if not key:
        raise RuntimeError("ADMIN_TOTP_KEY is not set; TOTP secrets cannot be stored safely.")
    return Fernet(key.encode())


def hash_password(password: str) -> str:
    return hasher.hash(password)


def verify_password(stored: str, password: str) -> bool:
    try:
        hasher.verify(stored, password)
        return True
    except (VerifyMismatchError, InvalidHashError):
        return False


def encrypt_totp(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_totp(blob: str) -> str:
    return _fernet().decrypt(blob.encode()).decode()


# --------------------------------------------------------------------------- #
# Rate limiting: per IP+account, so one attacker cannot lock out every user by
# hammering one IP, and one account cannot be brute-forced from many IPs.
# --------------------------------------------------------------------------- #

def _attempt_key(ip: str, email: str) -> str:
    return "fo:adm:rl:" + hashlib.sha256(f"{ip}|{email.lower()}".encode()).hexdigest()


def too_many_attempts(ip: str, email: str) -> bool:
    return int(_redis().get(_attempt_key(ip, email)) or 0) >= MAX_ATTEMPTS


def record_failure(ip: str, email: str) -> int:
    client, key = _redis(), _attempt_key(ip, email)
    count = client.incr(key)
    client.expire(key, int(ATTEMPT_WINDOW.total_seconds()))
    with tx(Role.ADMIN) as cur:
        # Exponential backoff on the account itself, so the lockout survives a
        # Redis flush and follows the user across IPs.
        cur.execute(
            """update ops.users
                  set failed_attempts = failed_attempts + 1,
                      locked_until = case when failed_attempts + 1 >= %s
                                          then now() + (interval '1 minute'
                                               * least(power(2, failed_attempts + 1 - %s), 60))
                                     end
                where email = %s and archived_at is null""",
            (MAX_ATTEMPTS, MAX_ATTEMPTS, email),
        )
    return count


def clear_failures(ip: str, email: str, user_id: int) -> None:
    _redis().delete(_attempt_key(ip, email))
    with tx(Role.ADMIN, actor_id=user_id) as cur:
        cur.execute(
            "update ops.users set failed_attempts = 0, locked_until = null, last_login_at = now() where id = %s",
            (user_id,),
        )


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #

def find_user(email: str) -> dict | None:
    with tx(Role.ADMIN) as cur:
        cur.execute(
            """select id, email::text as email, name, password_hash, role::text as role,
                      totp_secret_enc, totp_enabled, session_version, locked_until
                 from ops.users where email = %s and archived_at is null""",
            (email,),
        )
        return cur.fetchone()


def load_user(user_id: int) -> dict | None:
    with tx(Role.ADMIN) as cur:
        cur.execute(
            """select id, email::text as email, name, role::text as role, totp_enabled,
                      session_version
                 from ops.users where id = %s and archived_at is null""",
            (user_id,),
        )
        return cur.fetchone()


def create_user(email: str, name: str, password: str, role: str, actor_id: int | None = None) -> int:
    with tx(Role.ADMIN, actor_id=actor_id) as cur:
        cur.execute(
            """insert into ops.users (email, name, password_hash, role)
               values (%s, %s, %s, %s) returning id""",
            (email, name, hash_password(password), role),
        )
        return cur.fetchone()["id"]


def set_password(user_id: int, password: str, actor_id: int | None = None) -> None:
    with tx(Role.ADMIN, actor_id=actor_id) as cur:
        # Bumping session_version invalidates every live session for this user.
        cur.execute(
            """update ops.users
                  set password_hash = %s, session_version = session_version + 1,
                      failed_attempts = 0, locked_until = null
                where id = %s""",
            (hash_password(password), user_id),
        )
    current_app.session_interface.revoke_all_for(user_id)


def set_role(user_id: int, role: str, actor_id: int | None = None) -> None:
    with tx(Role.ADMIN, actor_id=actor_id) as cur:
        cur.execute(
            "update ops.users set role = %s, session_version = session_version + 1 where id = %s",
            (role, user_id),
        )
    current_app.session_interface.revoke_all_for(user_id)


# --------------------------------------------------------------------------- #
# Request wiring
# --------------------------------------------------------------------------- #

def attach_user() -> None:
    """Runs before every request. Rejects sessions that are stale in any sense."""
    g.user = None
    uid = session.get("uid")
    if not uid:
        return

    now = datetime.now(timezone.utc).timestamp()
    if now - session.get("started_at", 0) > ABSOLUTE_SECONDS:
        session.clear()
        return
    if now - session.get("seen_at", 0) > IDLE_SECONDS:
        session.clear()
        return

    user = load_user(uid)
    # A password or role change bumps session_version; every live session for
    # that user is refused on its very next request.
    if not user or user["session_version"] != session.get("sv"):
        session.clear()
        return

    session["seen_at"] = now
    g.user = user


def login_required_guard():
    """Deny by default at the request level, before routing-specific checks."""
    endpoint = request.endpoint or ""
    view = current_app.view_functions.get(endpoint)
    if view is not None and getattr(view, "__fo_public__", False):
        return None
    if endpoint.startswith("static") or endpoint in {"healthz", "readyz"}:
        return None
    if not g.get("user"):
        return redirect(url_for("auth.login", next=request.path))
    return None


def _start_session(user: dict) -> None:
    session.clear()
    now = datetime.now(timezone.utc).timestamp()
    session.update({
        "uid": user["id"], "sv": user["session_version"], "started_at": now, "seen_at": now,
    })


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

@bp.route("/login", methods=["GET", "POST"])
@public
def login():
    if g.get("user"):
        return redirect(url_for("dashboard.index"))
    if request.method == "GET":
        return render_template("login.html", page_title="Sign in")

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    ip = request.headers.get("CF-Connecting-IP") or request.remote_addr or "-"

    # One message for every failure mode. Distinguishing "no such user" from
    # "wrong password" hands an attacker a free account enumerator.
    generic = "Incorrect email or password."

    if too_many_attempts(ip, email):
        return render_template("login.html", error="Too many attempts. Try again later.",
                               page_title="Sign in"), 429

    user = find_user(email)
    if not user or not verify_password(user["password_hash"], password):
        record_failure(ip, email)
        return render_template("login.html", error=generic, page_title="Sign in"), 401
    if user["locked_until"] and user["locked_until"] > datetime.now(timezone.utc):
        return render_template("login.html", error="This account is temporarily locked.",
                               page_title="Sign in"), 429

    clear_failures(ip, email, user["id"])

    if user["totp_enabled"]:
        session.clear()
        session["pending_uid"] = user["id"]
        session["pending_at"] = datetime.now(timezone.utc).timestamp()
        return redirect(url_for("auth.totp_challenge"))

    if user["role"] in TOTP_REQUIRED_ROLES:
        session.clear()
        session["enroll_uid"] = user["id"]
        return redirect(url_for("auth.enroll"))

    _start_session(user)
    return redirect(request.args.get("next") or url_for("dashboard.index"))


@bp.route("/login/totp", methods=["GET", "POST"])
@public
def totp_challenge():
    uid = session.get("pending_uid")
    if not uid or datetime.now(timezone.utc).timestamp() - session.get("pending_at", 0) > 300:
        session.clear()
        return redirect(url_for("auth.login"))
    if request.method == "GET":
        return render_template("totp.html", page_title="Two-factor")

    user = load_user(uid)
    with tx(Role.ADMIN) as cur:
        cur.execute("select totp_secret_enc from ops.users where id = %s", (uid,))
        row = cur.fetchone()
    try:
        secret = decrypt_totp(row["totp_secret_enc"])
    except (InvalidToken, TypeError):
        log.error("TOTP secret for user %s cannot be decrypted; ADMIN_TOTP_KEY may have rotated", uid)
        abort(500)

    code = request.form.get("code", "").replace(" ", "")
    # valid_window=1 accepts the adjacent step, covering ordinary clock drift
    # without meaningfully widening the attack window.
    if not pyotp.TOTP(secret).verify(code, valid_window=1):
        ip = request.remote_addr or "-"
        record_failure(ip, user["email"])
        return render_template("totp.html", error="That code is not valid.", page_title="Two-factor"), 401

    user = find_user(user["email"])
    _start_session(user)
    return redirect(url_for("dashboard.index"))


@bp.route("/account/2fa", methods=["GET", "POST"])
@public
def enroll():
    """Mandatory enrolment for owner/manager, optional for everyone else."""
    uid = session.get("enroll_uid") or (g.user["id"] if g.get("user") else None)
    if not uid:
        return redirect(url_for("auth.login"))
    user = load_user(uid)

    if request.method == "POST":
        secret = session.get("enroll_secret", "")
        if not secret or not pyotp.TOTP(secret).verify(request.form.get("code", ""), valid_window=1):
            return render_template("enroll.html", user=user, secret=secret,
                                   qr=_qr_svg(user["email"], secret),
                                   error="That code is not valid yet -- try the next one.",
                                   page_title="Set up two-factor"), 401
        with tx(Role.ADMIN, actor_id=uid) as cur:
            cur.execute(
                "update ops.users set totp_secret_enc = %s, totp_enabled = true where id = %s",
                (encrypt_totp(secret), uid),
            )
        session.pop("enroll_secret", None)
        session.pop("enroll_uid", None)
        _start_session(find_user(user["email"]))
        return redirect(url_for("dashboard.index"))

    secret = session.get("enroll_secret") or pyotp.random_base32()
    session["enroll_secret"] = secret
    return render_template("enroll.html", user=user, secret=secret,
                           qr=_qr_svg(user["email"], secret), page_title="Set up two-factor")


def _qr_svg(email: str, secret: str) -> str:
    uri = pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name="Framed Obsessions")
    # Inline SVG: the CSP forbids remote images, and a QR service would leak the
    # TOTP secret to a third party.
    return segno.make(uri, error="m").svg_inline(scale=4, dark="#e8edf5", light=None)


@bp.post("/logout")
@public
def logout():
    uid = session.get("uid")
    session.clear()
    log.info("admin logout uid=%s", uid)
    return redirect(url_for("auth.login"))


@bp.route("/account/password", methods=["GET", "POST"])
@public
def change_password():
    if not g.get("user"):
        return redirect(url_for("auth.login"))
    if request.method == "GET":
        return render_template("password.html", page_title="Change password")

    current = request.form.get("current", "")
    new = request.form.get("new", "")
    user = find_user(g.user["email"])
    if not verify_password(user["password_hash"], current):
        return render_template("password.html", error="Current password is incorrect.",
                               page_title="Change password"), 401
    if len(new) < 12:
        return render_template("password.html", error="Use at least 12 characters.",
                               page_title="Change password"), 400
    set_password(user["id"], new, actor_id=user["id"])
    session.clear()
    return redirect(url_for("auth.login"))


def new_reset_token(user_id: int) -> str:
    """Emailed token. Only its SHA-256 is stored, single use, 30-minute TTL."""
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).digest()
    with tx(Role.ADMIN) as cur:
        cur.execute(
            """insert into ops.password_resets (user_id, token_hash, expires_at)
               values (%s, %s, now() + interval '30 minutes')""",
            (user_id, digest),
        )
    return token


def consume_reset_token(token: str) -> int | None:
    digest = hashlib.sha256(token.encode()).digest()
    with tx(Role.ADMIN) as cur:
        cur.execute(
            """update ops.password_resets set used_at = now()
                where token_hash = %s and used_at is null and expires_at > now()
             returning user_id""",
            (digest,),
        )
        row = cur.fetchone()
        return row["user_id"] if row else None


def generate_totp_key() -> str:
    """Helper for deployment docs: a fresh ADMIN_TOTP_KEY."""
    return base64.urlsafe_b64encode(os.urandom(32)).decode()
