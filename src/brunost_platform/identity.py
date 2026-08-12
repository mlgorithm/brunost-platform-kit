"""Replaceable identity adapters for standalone and embedded deployments."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from brunost_platform.models import User
from brunost_platform.store import SQLitePlatformStore


@dataclass
class LocalIdentityAdapter:
    """Minimal local identity projection for demos and small deployments.

    Production installations should normally use an OIDC/SAML adapter and keep
    authentication outside the judge and Platform Kit.
    """

    store: SQLitePlatformStore

    def provision(self, user: User) -> User:
        return self.store.save_user(user)

    def get_subject(self, request: Any) -> str | None:
        headers = getattr(request, "headers", request if isinstance(request, dict) else {})
        return headers.get("x-brunost-subject") or headers.get("x-user-id")


@dataclass
class ExternalIdentityAdapter:
    resolver: Callable[[Any], str | None]

    def get_subject(self, request: Any) -> str | None:
        return self.resolver(request)
