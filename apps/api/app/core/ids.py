"""Identifier helpers.

Prefixes keep ids greppable across the audit trail (``an_``, ``fd_``, ``ch_``…).
``stable_id`` is used for seeded content so re-seeding is idempotent.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone

_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def stable_id(prefix: str, *parts: object) -> str:
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:16]
    return f"{prefix}_{digest}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def short_code(n: int, width: int = 3) -> str:
    return str(n).zfill(width)
