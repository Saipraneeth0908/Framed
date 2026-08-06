"""Create the first admin account.

    python -m scripts.create_admin_user --email you@example.com --name "Your Name" --role owner

Password is read from ADMIN_BOOTSTRAP_PASSWORD, or generated and printed once.
Owner and manager accounts are forced through TOTP enrolment at first sign-in.
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--role", default="owner",
                        choices=["owner", "manager", "inventory", "fulfilment"])
    parser.add_argument("--reset", action="store_true",
                        help="Reset the password if the account already exists")
    args = parser.parse_args()

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
