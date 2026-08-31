"""Replaceable identity adapters for standalone and embedded deployments."""

from __future__ import annotations

import hashlib
import hmac
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from brunost_platform.models import User


@dataclass
class LocalIdentityAdapter:
    """Minimal local identity projection for demos and small deployments.

    Production installations should normally use an OIDC/SAML adapter and keep
    authentication outside the judge and Platform Kit.
    """

    store: Any

    def provision(self, user: User) -> User:
        return self.store.save_user(user)

    def register(
        self,
        *,
        email: str,
        password: str,
        display_name: str,
        roles: tuple[str, ...] = ("contestant",),
        metadata: dict[str, Any] | None = None,
    ) -> User:
        if len(password) < 10:
            raise ValueError("password must contain at least 10 characters")
        normalized = email.strip().lower()
        if not normalized or "@" not in normalized:
            raise ValueError("a valid email address is required")
        user = User(str(uuid.uuid4()), normalized, display_name.strip(), roles=roles, metadata=metadata or {}, password_hash=self.hash_password(password))
        return self.store.save_user(user)

    def change_password(self, *, user_id: str, current_password: str, new_password: str) -> User:
        """Change a local password and clear any first-login password flag."""
        if len(new_password) < 10:
            raise ValueError("password must contain at least 10 characters")
        user = self.store.get_user(user_id)
        if user is None or not user.password_hash or not self.verify_password(current_password, user.password_hash):
            raise ValueError("current password is incorrect")
        metadata = {**user.metadata, "must_change_password": False}
        updated = User(
            user.user_id,
            user.email,
            user.display_name,
            user.organization_id,
            user.roles,
            metadata,
            self.hash_password(new_password),
        )
        result = self.store.save_user(updated)
        self.store.delete_user_sessions(user_id)
        return result

    def authenticate(self, *, email: str, password: str, ttl_seconds: int = 86400) -> str | None:
        user = self.store.get_user_by_email(email)
        if not user or user.metadata.get("disabled") or not user.password_hash or not self.verify_password(password, user.password_hash):
            return None
        if ttl_seconds < 1:
            raise ValueError("session TTL must be positive")
        return self.store.create_session(user.user_id, ttl_seconds=ttl_seconds)

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
    """Bridge an external identity provider into a small platform projection.

    The resolver belongs to the embedding application (OIDC, SAML, an LMS,
    or Brunost Premium).  The Judge and Platform Kit never receive external
    passwords or tokens; they only see this opaque subject and its roles.
    """

    resolver: Callable[[Any], ExternalPrincipal | dict[str, Any] | str | None]

    def resolve(self, request: Any) -> ExternalPrincipal | None:
        value = self.resolver(request)
        if value is None:
            return None
        if isinstance(value, ExternalPrincipal):
            return value
        if isinstance(value, str):
            return ExternalPrincipal(subject_id=value)
        if isinstance(value, dict):
            subject = value.get("subject_id") or value.get("sub") or value.get("user_id")
            if not subject:
                return None
            raw_roles = value.get("roles", ())
            if isinstance(raw_roles, str):
                raw_roles = (raw_roles,)
            roles = tuple(str(role).strip() for role in raw_roles if str(role).strip())
            known = {"subject_id", "sub", "user_id", "email", "display_name", "roles", "organization_id", "metadata"}
            metadata = dict(value.get("metadata") or {})
            metadata.update({key: item for key, item in value.items() if key not in known})
            return ExternalPrincipal(
                subject_id=str(subject),
                email=str(value["email"]) if value.get("email") else None,
                display_name=str(value["display_name"]) if value.get("display_name") else None,
                roles=roles,
                organization_id=str(value["organization_id"]) if value.get("organization_id") else None,
                metadata=metadata,
            )
        raise TypeError("identity resolver must return ExternalPrincipal, a mapping, a subject string, or None")

    def get_subject(self, request: Any) -> str | None:
        principal = self.resolve(request)
        return principal.subject_id if principal else None


@dataclass(frozen=True)
class ExternalPrincipal:
    """Non-sensitive identity data projected by an embedding platform."""

    subject_id: str
    email: str | None = None
    display_name: str | None = None
    roles: tuple[str, ...] = ()
    organization_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
