"""Minimal platform-side domain objects.

These objects are deliberately not persistence models.  A generated project
can map them to SQLAlchemy, Django ORM, Prisma, or an existing LMS database.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Contest:
    contest_id: str
    name: str
    task_refs: tuple[str, ...] = ()
    status: str = "draft"
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["task_refs"] = list(self.task_refs)
        return value


@dataclass(frozen=True)
class Submission:
    submission_id: str
    contestant_id: str
    task_ref: str
    artifact_path: str
    contest_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LeaderboardEntry:
    contestant_id: str
    contest_id: str
    task_ref: str
    score: float | None
    evaluation_id: str
    visible: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class User:
    """Platform-owned identity projection; authentication may remain external."""

    user_id: str
    email: str
    display_name: str
    organization_id: str | None = None
    roles: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["roles"] = list(self.roles)
        return value
