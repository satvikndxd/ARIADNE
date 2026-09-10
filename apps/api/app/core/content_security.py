"""Prompt-injection defence: documents are DATA, never instructions.

Retrieved text is scanned for instruction-shaped content.  Hits do not cause
deletion of the chunk — they cause it to be *quarantined*: it can still be
shown to a human (transparency) but is excluded from evidence synthesis and
from anything that reaches the model as context, and the UI badges it.
"""
from __future__ import annotations

import re

_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+|any\s+)?(previous|prior|above|earlier)\s+(instructions|prompts|rules)",
    r"disregard\s+(all\s+|any\s+)?(previous|prior|your)\s+(instructions|rules|guidelines)",
    r"you\s+are\s+now\s+(a|an|the)\s+",
    r"new\s+system\s+prompt",
    r"reveal\s+(the\s+|your\s+)?(system\s+prompt|instructions|hidden)",
    r"delete\s+(all|every)\s+(findings|records|data)",
    r"approve\s+(all|every)\s+(changes|findings)\s+without",
    r"set\s+severity\s+of\s+all",
    r"override\s+(the\s+)?(reviewer|human|safety)",
    r"approve\s+(this|the|all|every)\s+(drawing|change|revision|finding|document)",
    r"(auto|matically)?\s*approve\s+without\s+(review|check)",
    r"(drawings?|documents?)\s+(are|is)\s+pre-approved",
]
_COMPILED = [re.compile(p, re.IGNORECASE) for p in _INJECTION_PATTERNS]


def scan_for_injection(text: str) -> list[str]:
    return [p.pattern for p in _COMPILED if p.search(text)]


def is_untrusted_authority(authority: str) -> bool:
    return authority in {"untrusted_vendor_note", "untrusted", "external_unverified"}


def quarantine_reason(text: str, authority: str) -> str | None:
    hits = scan_for_injection(text)
    if hits:
        return f"instruction-shaped content detected ({len(hits)} pattern(s))"
    if is_untrusted_authority(authority):
        return f"authority '{authority}' is excluded from evidence synthesis"
    return None
