"""Optional platform integrations.

The protocols let an organization keep its own users, email, and leaderboard
while using the generated application and the public judge.
"""

from __future__ import annotations

from typing import Any, Protocol

from brunost_platform.models import LeaderboardEntry


class IdentityAdapter(Protocol):
    def get_subject(self, request: Any) -> str | None: ...


class NotificationAdapter(Protocol):
    def send(self, *, recipient: str, subject: str, body: str) -> None: ...


class LeaderboardAdapter(Protocol):
    def record(self, entry: LeaderboardEntry) -> None: ...


class NullLeaderboard:
    """Safe default for installations that only use the judge API."""

    def record(self, entry: LeaderboardEntry) -> None:
        _ = entry
