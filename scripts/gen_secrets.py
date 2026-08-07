"""Fill in any missing secrets in deploy/.env. Never overwrites an existing one.

    python -m scripts.gen_secrets

This used to be a heredoc in the README that rewrote the whole file, which made
running setup twice quietly destructive:

  * ADMIN_SECRET_KEY changes  -> every session cookie is refused, so everyone is
    bounced to the login screen.
  * ADMIN_TOTP_KEY changes    -> every ops.users.totp_secret_enc becomes
    undecryptable, so every enrolled authenticator stops working and there is no
    logged-in session left to fix it from.

Together those two look exactly like "it asked me to log in again and my
two-factor is broken", with nothing in the logs pointing at the .env file. So
this only ever adds keys. Rotating one is a deliberate act -- see the runbook,
which says what breaks and how to recover.
"""

from __future__ import annotations

import secrets
from base64 import urlsafe_b64encode
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / "deploy" / ".env"

# Fernet needs exactly 32 url-safe base64 bytes; the rest are opaque.
GENERATORS = {
    "WEB_SECRET_KEY": lambda: secrets.token_urlsafe(48),
    "ADMIN_SECRET_KEY": lambda: secrets.token_urlsafe(48),
    "EVENT_SALT_SEED": lambda: secrets.token_urlsafe(32),
    "ADMIN_TOTP_KEY": lambda: urlsafe_b64encode(secrets.token_bytes(32)).decode(),
    "METABASE_EMBED_SECRET": lambda: secrets.token_hex(32),
    "GRAFANA_PASSWORD": lambda: secrets.token_urlsafe(18),
}


def main() -> int:
    ENV.parent.mkdir(parents=True, exist_ok=True)
    text = ENV.read_text(encoding="utf-8") if ENV.exists() else ""

    lines = text.splitlines()
    filled, kept = [], 0
    for i, line in enumerate(lines):
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or key not in GENERATORS:
            continue
        if value.strip():
            kept += 1
        else:
            # Present but blank. Fill it where it sits rather than appending a
            # second line for the same key -- .env is read last-wins, so a
            # duplicate works and reads like a bug.
            lines[i] = f"{key}={GENERATORS[key]()}"
            filled.append(key)

    seen = {line.partition("=")[0].strip() for line in lines}
    added = {k: make() for k, make in GENERATORS.items() if k not in seen}

    if not filled and not added:
        print(f"{ENV}: all {len(GENERATORS)} secrets already set, nothing to do.")
        return 0

    lines += [f"{k}={v}" for k, v in added.items()]
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")

    for key in [*filled, *added]:
        print(f"generated {key}")
    print(f"{ENV}: {kept} kept, {len(filled) + len(added)} generated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
