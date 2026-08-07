"""Create the first admin account, or recover one nobody can sign into.

    python -m scripts.create_admin_user --email you@example.com --name "Your Name" --role owner
    python -m scripts.create_admin_user --email you@example.com --name "" --reset-totp

Password is read from ADMIN_BOOTSTRAP_PASSWORD, or generated and printed once.
Owner and manager accounts are forced through TOTP enrolment at first sign-in.

``--reset-totp`` clears the enrolment so the next sign-in shows the QR code
again. It is the way out of the two situations the panel cannot fix from
inside itself: a lost authenticator, and an ADMIN_TOTP_KEY that has been
rotated out from under the stored secrets. Both leave every owner locked out,
and the only screen that could re-enrol them is behind the login they cannot
complete.
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from admin.auth import create_user, hash_password  # noqa: E402
from db.conn import Role, tx  # noqa: E402


def reset_totp(email: str) -> int:
    with tx(Role.SUPER) as cur:
        # session_version bumps so a session opened before the reset cannot be
        # the thing that re-enrols: whoever does it has to prove the password.
        cur.execute(
            """update ops.users
                  set totp_secret_enc = null, totp_enabled = false,
                      session_version = session_version + 1,
                      failed_attempts = 0, locked_until = null
                where email = %s and archived_at is null
            returning id, role""",
            (email,),
        )
        row = cur.fetchone()

    if not row:
        print(f"no active account for {email}")
        return 1
    print(f"two-factor cleared for {email} (id {row['id']}, role {row['role']})")
    print("Live sessions for this account are now refused.")
    print("Next sign-in with the existing password shows the QR code again.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default="")
    parser.add_argument("--role", default="owner",
                        choices=["owner", "manager", "inventory", "fulfilment"])
    parser.add_argument("--reset", action="store_true",
                        help="Reset the password if the account already exists")
    parser.add_argument("--reset-totp", action="store_true",
                        help="Clear the two-factor enrolment; the next sign-in re-enrols")
    args = parser.parse_args()

    if args.reset_totp:
        return reset_totp(args.email)
    if not args.name:
        parser.error("--name is required unless you are passing --reset-totp")

    password = os.environ.get("ADMIN_BOOTSTRAP_PASSWORD") or secrets.token_urlsafe(18)

    with tx(Role.SUPER) as cur:
        cur.execute("select id from ops.users where email = %s and archived_at is null", (args.email,))
        existing = cur.fetchone()
        if existing and not args.reset:
            print(f"{args.email} already exists (id {existing['id']}). Pass --reset to set a new password.")
            return 1
        if existing:
            cur.execute(
                """update ops.users
                      set password_hash = %s, session_version = session_version + 1,
                          failed_attempts = 0, locked_until = null
                    where id = %s""",
                (hash_password(password), existing["id"]),
            )
            user_id = existing["id"]
        else:
            user_id = None

    if user_id is None:
        user_id = create_user(args.email, args.name, password, args.role)

    print(f"admin id={user_id} email={args.email} role={args.role}")
    if not os.environ.get("ADMIN_BOOTSTRAP_PASSWORD"):
        print(f"password: {password}")
        print("This is shown once. Store it in a password manager now.")
    if args.role in {"owner", "manager"}:
        print("Two-factor setup is mandatory and will be requested at first sign-in.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
