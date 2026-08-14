"""Edition and capability policy shared by standalone and Premium deployments.

The policy is deliberately small and data-oriented.  A Premium application can
keep its own users/courses database and pass a ``User`` projection with roles;
the contest core then applies the same authorization rules as the standalone
reference application.  Features are never removed from the API by edition --
the standalone profile simply does not expose the optional global-library UI.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from brunost_platform.models import User

CREATE_CONTEST = "contest.create"
MANAGE_CONTEST = "contest.manage"
CREATE_NESTED_TASK = "contest.task.create"
GLOBAL_TASK_LIBRARY = "task.global-library"
COURSES = "courses"
USER_CREATED_CONTESTS = "contest.user-created"


@dataclass(frozen=True)
class PlatformPolicy:
    """Authorization profile for the open-source core or Brunost Premium."""

    edition: str = "standalone"
    enabled_features: frozenset[str] = frozenset()

    @classmethod
    def from_environment(cls) -> PlatformPolicy:
        edition = os.environ.get("BRUNOST_PLATFORM_EDITION", "standalone").strip().lower() or "standalone"
        if edition not in {"standalone", "advanced"}:
            raise ValueError("BRUNOST_PLATFORM_EDITION must be standalone or advanced")
        raw = os.environ.get("BRUNOST_PLATFORM_FEATURES", "")
        explicit = frozenset(item.strip() for item in raw.split(",") if item.strip())
        return cls(edition, explicit)

    @property
    def is_advanced(self) -> bool:
        return self.edition == "advanced"

    @property
    def global_task_library_enabled(self) -> bool:
        return self.is_advanced or GLOBAL_TASK_LIBRARY in self.enabled_features

    @property
    def courses_enabled(self) -> bool:
        return self.is_advanced or COURSES in self.enabled_features

    def enabled(self, capability: str) -> bool:
        if capability in self.enabled_features:
            return True
        if self.is_advanced and capability in {GLOBAL_TASK_LIBRARY, COURSES, USER_CREATED_CONTESTS}:
            return True
        return capability in {CREATE_CONTEST, MANAGE_CONTEST, CREATE_NESTED_TASK}

    def can_create_contest(self, actor: User | Any) -> bool:
        roles = self._roles(actor)
        if "admin" in roles:
            return True
        if not self.enabled(USER_CREATED_CONTESTS):
            return False
        return bool(roles.intersection({"organizer", "teacher", "contest_creator", "owner"}))

    def can_manage_contest(self, actor: User | Any) -> bool:
        roles = self._roles(actor)
        return bool(roles.intersection({"admin", "organizer", "teacher", "contest_creator", "owner", "grader"}))

    def can_manage_platform(self, actor: User | Any) -> bool:
        roles = self._roles(actor)
        if self.is_advanced:
            return bool(roles.intersection({"admin", "organizer", "teacher", "contest_creator"}))
        return "admin" in roles

    def can_create_global_task(self, actor: User | Any) -> bool:
        return self.global_task_library_enabled and self.can_manage_platform(actor)

    @staticmethod
    def _roles(actor: User | Any) -> set[str]:
        return {str(role).strip().lower() for role in getattr(actor, "roles", ()) if str(role).strip()}

