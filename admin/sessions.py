"""Server-side sessions in Redis.

Flask's default cookie session cannot be revoked: a stolen cookie is valid until
it expires, whatever the server does. Storing state in Redis and putting only an
opaque id in the cookie makes revocation instant -- which is the requirement for
an admin panel with a password-reset and role-change story.

Sixty lines instead of Flask-Session, which drags in more surface than it saves.
"""

from __future__ import annotations

import json
import os
import secrets
from datetime import timedelta

import redis
from flask.sessions import SessionInterface, SessionMixin

IDLE_TIMEOUT = timedelta(minutes=30)
ABSOLUTE_TIMEOUT = timedelta(hours=12)
PREFIX = "fo:adm:sess:"


class RedisSession(dict, SessionMixin):
    def __init__(self, initial=None, sid=None, new=False):
        super().__init__(initial or {})
        self.sid = sid
        self.new = new
        self.modified = False

    # Every mutating dict method has to flip `modified`, not just __setitem__:
    # dict.update() and dict.setdefault() do NOT route through __setitem__, so
    # overriding only that one silently drops writes -- including the whole of
    # _start_session(), which uses update().
    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.modified = True

    def __delitem__(self, key):
        super().__delitem__(key)
        self.modified = True

    def pop(self, key, *args):
        self.modified = True
        return super().pop(key, *args)

    def popitem(self):
        self.modified = True
        return super().popitem()

    def setdefault(self, key, default=None):
        self.modified = True
        return super().setdefault(key, default)

    def update(self, *args, **kwargs):
        super().update(*args, **kwargs)
        self.modified = True

    def clear(self):
        super().clear()
        self.modified = True


class RedisSessionInterface(SessionInterface):
    def __init__(self, url: str | None = None):
        self.client = redis.from_url(url or os.environ.get("REDIS_URL", "redis://localhost:6380/0"))

    def open_session(self, app, request):
        sid = request.cookies.get(app.config["SESSION_COOKIE_NAME"])
        if not sid:
            return RedisSession(sid=secrets.token_urlsafe(32), new=True)
        raw = self.client.get(PREFIX + sid)
        if raw is None:
            # Expired or revoked. A fresh id, not the old one -- reusing it
            # would let an attacker pin a session id before login.
            return RedisSession(sid=secrets.token_urlsafe(32), new=True)
        return RedisSession(json.loads(raw), sid=sid)

    def save_session(self, app, session, response):
        name = app.config["SESSION_COOKIE_NAME"]
        domain = self.get_cookie_domain(app)
        if not session:
            if not session.new:
                self.client.delete(PREFIX + session.sid)
                response.delete_cookie(name, domain=domain, path="/")
            return
        if not (session.modified or session.new):
            # Sliding idle window: touch the TTL even on a read-only request.
            self.client.expire(PREFIX + session.sid, int(IDLE_TIMEOUT.total_seconds()))
            return
        self.client.setex(
            PREFIX + session.sid, int(IDLE_TIMEOUT.total_seconds()), json.dumps(dict(session))
        )
        response.set_cookie(
            name, session.sid,
            max_age=int(ABSOLUTE_TIMEOUT.total_seconds()),
            httponly=True,
            secure=self.get_cookie_secure(app),
            samesite=self.get_cookie_samesite(app),
            domain=domain,
            path="/",
        )

    def revoke_all_for(self, user_id: int) -> int:
        """Belt to session_version's braces -- drops the stored sessions too."""
        dropped = 0
        for key in self.client.scan_iter(PREFIX + "*"):
            raw = self.client.get(key)
            if raw and json.loads(raw).get("uid") == user_id:
                self.client.delete(key)
                dropped += 1
        return dropped
