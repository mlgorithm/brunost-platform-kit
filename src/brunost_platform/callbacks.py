"""Verification and replay protection for Brunost Judge callbacks.

The kit keeps this helper framework-neutral: a FastAPI, Django, Flask, or
Node adapter can pass the raw request body and header mapping without sharing
database models with the judge.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Mapping


def verify_judge_callback(
    body: bytes,
    headers: Mapping[str, str],
    secret: str,
    *,
    tolerance_seconds: int = 300,
) -> str | None:
    """Return the signed event ID, or ``None`` when verification fails."""
    normalized = {str(key).lower(): str(value) for key, value in headers.items()}
    event_id = normalized.get("x-brunost-judge-event-id", "").strip()
    timestamp = normalized.get("x-brunost-judge-timestamp", "").strip()
    signature = normalized.get("x-brunost-judge-signature", "").strip()
    if not event_id or not timestamp or not signature:
        return None
    try:
        sent_at = int(timestamp)
    except ValueError:
        return None
    if abs(int(time.time()) - sent_at) > tolerance_seconds:
        return None
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"),
        f"{sent_at}.{event_id}.".encode() + body,
        hashlib.sha256,
    ).hexdigest()
    return event_id if hmac.compare_digest(expected, signature) else None
