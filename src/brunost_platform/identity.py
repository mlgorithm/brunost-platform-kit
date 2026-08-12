"""Replaceable identity adapters for standalone and embedded deployments."""

from __future__ import annotations

import hashlib
import hmac
import os
import uuid
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

    def register(self, *, email: str, password: str, display_name: str, roles: tuple[str, ...] = ("contestant",)) -> User:
        if len(password) < 10:
            raise ValueError("password must contain at least 10 characters")
        normalized = email.strip().lower()
        if not normalized or "@" not in normalized:
            raise ValueError("a valid email address is required")
        user = User(str(uuid.uuid4()), normalized, display_name.strip(), roles=roles, password_hash=self.hash_password(password))
        return self.store.save_user(user)

    def authenticate(self, *, email: str, password: str) -> str | None:
        user = self.store.get_user_by_email(email)
        if not user or not user.password_hash or not self.verify_password(password, user.password_hash):
            return None
        return self.store.create_session(user.user_id)

    @staticmethod
    def hash_password(password: str) -> str:
        salt = os.urandom(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 260_000)
        return f"pbkdf2_sha256$260000${salt.hex()}${digest.hex()}"

    @staticmethod
    def verify_password(password: str, encoded: str) -> bool:
        try:
            algorithm, iterations, salt, expected = encoded.split("$", 3)
            if algorithm != "pbkdf2_sha256":
                return False
            actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations)).hex()
            return hmac.compare_digest(actual, expected)
        except (TypeError, ValueError):
            return False

    def get_subject(self, request: Any) -> str | None:
        headers = getattr(request, "headers", request if isinstance(request, dict) else {})
        return headers.get("x-brunost-subject") or headers.get("x-user-id")


@dataclass
class ExternalIdentityAdapter:
    resolver: Callable[[Any], str | None]

    def get_subject(self, request: Any) -> str | None:
        return self.resolver(request)
