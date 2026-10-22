"""Who can see what.

    public   (no login)   screens outside each mess, and the student page for phones
    manager  (password)   everything: dashboard, food status (running low / out),
                          live spreadsheet, uploads, exports

Only the mess manager logs in. The password comes from the environment
(MESSQ_MANAGER_PASSWORD), never from files in the repo. If it isn't set, a random
password is made at start-up and printed in the terminal. Sessions are
HMAC-signed cookies (HttpOnly, SameSite=Strict) that end when the demo restarts.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from collections import defaultdict, deque

ROLES = ("manager",)
ENV = {"manager": "MESSQ_MANAGER_PASSWORD"}
SESSION_HOURS = 12
COOKIE = "messq_session"
MAX_ATTEMPTS = 8  # failed logins per address per 5 minutes


def _readable_password() -> str:
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"  # no look-alikes (l/1, o/0)
    return "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3))


class Auth:
    def __init__(self, passwords: dict[str, str] | None = None):
        self.generated: dict[str, str] = {}
        self.passwords: dict[str, str] = {}
        for role in ROLES:
            pw = (passwords or {}).get(role) or os.environ.get(ENV[role], "")
            if not pw:
                pw = _readable_password()
                self.generated[role] = pw
            self.passwords[role] = pw
        self._secret = secrets.token_bytes(32)
        self._fails: dict[str, deque[float]] = defaultdict(deque)

    # ---- login --------------------------------------------------------------
    def blocked(self, addr: str) -> bool:
        q = self._fails[addr]
        while q and q[0] < time.time() - 300:
            q.popleft()
        return len(q) >= MAX_ATTEMPTS

    def login(self, addr: str, password: str) -> str | None:
        """Role for this password, or None. Checks every role in constant time."""
        if self.blocked(addr):
            return None
        role = None
        for r in ROLES:
            if hmac.compare_digest(password.encode(), self.passwords[r].encode()):
                role = r
        if role is None:
            self._fails[addr].append(time.time())
        return role

    # ---- sessions -----------------------------------------------------------
    def _sign(self, payload: str) -> str:
        return hmac.new(self._secret, payload.encode(), hashlib.sha256).hexdigest()

    def make_cookie(self, role: str) -> str:
        payload = f"{role}.{int(time.time()) + SESSION_HOURS * 3600}.{secrets.token_hex(8)}"
        return f"{COOKIE}={payload}.{self._sign(payload)}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_HOURS * 3600}"

    @staticmethod
    def clear_cookie() -> str:
        return f"{COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"

    def role_from(self, cookie_header: str | None) -> str | None:
        if not cookie_header:
            return None
        for part in cookie_header.split(";"):
            name, _, value = part.strip().partition("=")
            if name != COOKIE:
                continue
            payload, _, sig = value.rpartition(".")
            if not payload or not hmac.compare_digest(sig, self._sign(payload)):
                return None
            role, expires, _nonce = (payload.split(".") + ["", ""])[:3]
            if role in ROLES and expires.isdigit() and int(expires) > time.time():
                return role
        return None
