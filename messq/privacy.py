"""Pseudonymisation of student IDs (DPDP Act 2023: minimise personal data).

Raw IDs are replaced with a keyed hash (HMAC-SHA256) before anything is stored.
Without the secret salt the hash can't be reversed by brute-forcing the small
space of roll numbers. Keep the salt in an environment variable, never in git.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import warnings


def pseudonymise(raw_id: str, salt: bytes) -> str:
    return hmac.new(salt, raw_id.strip().encode(), hashlib.sha256).hexdigest()[:16]


def load_salt(env_var: str = "MESSQ_ID_SALT") -> bytes:
    value = os.environ.get(env_var)
    if value:
        return value.encode()
    warnings.warn(
        f"{env_var} is not set; using a random per-process salt. Student keys will not "
        "be stable across restarts (fine for simulation, not for real data).",
        stacklevel=2,
    )
    return secrets.token_bytes(32)
