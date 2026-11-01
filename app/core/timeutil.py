"""Naive-UTC time helpers (DEC-005: every stored timestamp is naive UTC).

`datetime.utcnow()` is deprecated since Python 3.12; these helpers keep the
historical naive-UTC representation without the deprecated calls, in one
place instead of a dozen.
"""
from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def utc_from_timestamp(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, UTC).replace(tzinfo=None)


def to_naive_utc(value: datetime) -> datetime:
    """Aware -> naive UTC; naive values are assumed to already be UTC."""
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
