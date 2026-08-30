"""Typed, versioned contracts for the Premium-to-Judge boundary.

The contracts in this module intentionally use only the Python standard
library.  They model the stable parts of the Brunost Judge 1.3.x HTTP API
without making the Platform Kit depend on a particular Judge implementation.

The ``to_payload`` methods produce the wire shapes used by Judge 1.3.x.  The
``from_payload`` methods are deliberately tolerant of additive fields so an
application can consume a newer Judge result without having to upgrade the
Platform Kit at the same time.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any


class ContractValidationError(ValueError):
    """Raised when a platform/Judge contract cannot be represented safely."""


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/_-]*$")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_MAX_ID_LENGTH = 256
_MAX_METADATA_BYTES = 64 * 1024


def _required_text(value: Any, field_name: str, *, max_length: int = _MAX_ID_LENGTH) -> str:
    if not isinstance(value, str):
        raise ContractValidationError(f"{field_name} must be a string")
    value = value.strip()
    if not value:
        raise ContractValidationError(f"{field_name} must not be empty")
    if len(value) > max_length:
        raise ContractValidationError(f"{field_name} must be at most {max_length} characters")
    if not _IDENTIFIER.fullmatch(value):
        raise ContractValidationError(f"{field_name} contains unsupported characters")
    return value


def _optional_text(value: Any, field_name: str, *, max_length: int = _MAX_ID_LENGTH) -> str | None:
    if value is None:
        return None
    return _required_text(value, field_name, max_length=max_length)


def _optional_label(value: Any, field_name: str, *, max_length: int = _MAX_ID_LENGTH) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field_name} must not be empty")
    value = value.strip()
    if len(value) > max_length:
        raise ContractValidationError(f"{field_name} must be at most {max_length} characters")
    return value


def _artifact_id(value: Any, field_name: str = "artifact_id") -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value.strip()):
        raise ContractValidationError(f"{field_name} must be a 64-character SHA-256 hex digest")
    return value.strip().lower()


def _metadata(value: Mapping[str, Any] | None, field_name: str = "metadata") -> Mapping[str, Any]:
    if value is None:
        value = {}
    if not isinstance(value, Mapping):
        raise ContractValidationError(f"{field_name} must be an object")
    try:
        encoded = json.dumps(dict(value), sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"{field_name} must contain JSON-compatible values") from exc
    if len(encoded.encode("utf-8")) > _MAX_METADATA_BYTES:
        raise ContractValidationError(f"{field_name} must be at most {_MAX_METADATA_BYTES} bytes")
    # A shallow immutable copy protects the contract object from the common
    # accidental mutation.  ``to_payload`` creates a normal dict for JSON.
    return MappingProxyType(dict(value))


def _json_object(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractValidationError(f"{field_name} must be an object")
    return _metadata(value, field_name)


def _finite_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"{field_name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ContractValidationError(f"{field_name} must be a finite number")
    return result


def _copy_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return dict(value)


@dataclass(frozen=True)
class TaskRegistration:
    """A Judge task package registration.

    Production registrations use ``artifact_id``.  ``path`` remains available
    for local development and compatibility with Judge's 1.3.x development
    endpoint, but the two references are mutually exclusive.
    """

    task_ref: str
    kind: str
    artifact_id: str | None = None
    path: str | None = None
    runtime: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    version: int = 1
    evaluator: str | None = None
    resource_profile: Mapping[str, Any] = field(default_factory=dict)
    required_capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_ref", _required_text(self.task_ref, "task_ref"))
        object.__setattr__(self, "kind", _required_text(self.kind, "kind"))
        if bool(self.artifact_id) == bool(self.path):
            raise ContractValidationError("exactly one of artifact_id or path is required")
        if self.artifact_id is not None:
            object.__setattr__(self, "artifact_id", _artifact_id(self.artifact_id))
        if self.path is not None:
            if not isinstance(self.path, str) or not self.path.strip():
                raise ContractValidationError("path must not be empty")
            if len(self.path) > 1000:
                raise ContractValidationError("path must be at most 1000 characters")
            object.__setattr__(self, "path", self.path.strip())
        object.__setattr__(self, "runtime", _optional_text(self.runtime, "runtime"))
        object.__setattr__(self, "metadata", _metadata(self.metadata))
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ContractValidationError("version must be a positive integer")
        object.__setattr__(self, "evaluator", _optional_text(self.evaluator, "evaluator"))
        object.__setattr__(self, "resource_profile", _json_object(self.resource_profile, "resource_profile"))
        capabilities = tuple(_required_text(value, "required_capabilities entry", max_length=100) for value in self.required_capabilities)
        if len(capabilities) > 32:
            raise ContractValidationError("required_capabilities must contain at most 32 entries")
        object.__setattr__(self, "required_capabilities", capabilities)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"task_ref": self.task_ref, "kind": self.kind, "metadata": _copy_mapping(self.metadata)}
        if self.artifact_id is not None:
            payload["artifact_id"] = self.artifact_id
        if self.path is not None:
            payload["path"] = self.path
        if self.runtime is not None:
            payload["runtime"] = self.runtime
        if self.version != 1:
            payload["version"] = self.version
        if self.evaluator is not None:
            payload["evaluator"] = self.evaluator
        if self.resource_profile:
            payload["resource_profile"] = _copy_mapping(self.resource_profile)
        if self.required_capabilities:
            payload["required_capabilities"] = list(self.required_capabilities)
        return payload


@dataclass(frozen=True)
class ArtifactSubmission:
    """An immutable platform submission represented by a content-addressed artifact."""

    submission_id: str
    contestant_id: str
    task_ref: str
    artifact_id: str
    contest_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in ("submission_id", "contestant_id", "task_ref"):
            object.__setattr__(self, field_name, _required_text(getattr(self, field_name), field_name))
        object.__setattr__(self, "artifact_id", _artifact_id(self.artifact_id))
        object.__setattr__(self, "contest_id", _optional_text(self.contest_id, "contest_id"))
        object.__setattr__(self, "metadata", _metadata(self.metadata))

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "submission_id": self.submission_id,
            "contestant_id": self.contestant_id,
            "task_ref": self.task_ref,
            "submission_artifact_id": self.artifact_id,
            "metadata": _copy_mapping(self.metadata),
        }
        if self.contest_id is not None:
            payload["contest_id"] = self.contest_id
        return payload


@dataclass(frozen=True)
class EvaluationRequest:
    """A Judge 1.3.x evaluation request backed by an immutable artifact."""

    task_ref: str
    submission_artifact_id: str
    idempotency_key: str
    evaluation_kind: str = "batch"
    agent_refs: tuple[str, ...] = ()
    game_ref: str | None = None
    seed: int | None = None
    callback_url: str | None = None
    callback_token: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    queue: str = "default"
    resource_class: str = "cpu"
    priority: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_ref", _required_text(self.task_ref, "task_ref"))
        object.__setattr__(self, "submission_artifact_id", _artifact_id(self.submission_artifact_id, "submission_artifact_id"))
        object.__setattr__(self, "idempotency_key", _required_text(self.idempotency_key, "idempotency_key"))
        object.__setattr__(self, "evaluation_kind", _required_text(self.evaluation_kind, "evaluation_kind"))
        refs = tuple(_required_text(value, "agent_refs entry") for value in self.agent_refs)
        object.__setattr__(self, "agent_refs", refs)
        object.__setattr__(self, "game_ref", _optional_text(self.game_ref, "game_ref"))
        if self.seed is not None and (isinstance(self.seed, bool) or not isinstance(self.seed, int)):
            raise ContractValidationError("seed must be an integer")
        object.__setattr__(self, "callback_url", self._optional_url(self.callback_url, "callback_url"))
        if self.callback_token is not None:
            if not isinstance(self.callback_token, str) or not self.callback_token.strip():
                raise ContractValidationError("callback_token must not be empty")
            object.__setattr__(self, "callback_token", self.callback_token.strip())
        object.__setattr__(self, "metadata", _metadata(self.metadata))
        object.__setattr__(self, "queue", _required_text(self.queue, "queue"))
        object.__setattr__(self, "resource_class", _required_text(self.resource_class, "resource_class"))
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise ContractValidationError("priority must be an integer")
        object.__setattr__(self, "priority", self.priority)

    @staticmethod
    def _optional_url(value: str | None, field_name: str) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 2048:
            raise ContractValidationError(f"{field_name} must be a valid non-empty URL")
        value = value.strip()
        if "://" not in value:
            raise ContractValidationError(f"{field_name} must include a URL scheme")
        return value

    @classmethod
    def from_submission(
        cls,
        submission: ArtifactSubmission,
        *,
        idempotency_key: str | None = None,
        **options: Any,
    ) -> EvaluationRequest:
        """Create an evaluation request without re-copying submission fields."""
        return cls(
            task_ref=submission.task_ref,
            submission_artifact_id=submission.artifact_id,
            idempotency_key=idempotency_key or submission.submission_id,
            metadata={**dict(submission.metadata), **dict(options.pop("metadata", {}) or {})},
            **options,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "task_ref": self.task_ref,
            "submission_artifact_id": self.submission_artifact_id,
            "idempotency_key": self.idempotency_key,
            "evaluation_kind": self.evaluation_kind,
            "agent_refs": list(self.agent_refs),
            "game_ref": self.game_ref,
            "seed": self.seed,
            "callback_url": self.callback_url,
            "callback_token": self.callback_token,
            "metadata": _copy_mapping(self.metadata),
            "queue": self.queue,
            "resource_class": self.resource_class,
            "priority": self.priority,
        }


@dataclass(frozen=True)
class ResultArtifact:
    """A content-addressed artifact returned by an evaluation."""

    artifact_id: str
    name: str | None = None
    media_type: str | None = None
    size_bytes: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_id", _artifact_id(self.artifact_id))
        object.__setattr__(self, "name", _optional_label(self.name, "artifact name", max_length=512))
        object.__setattr__(self, "media_type", self.media_type.strip() if isinstance(self.media_type, str) and self.media_type.strip() else None)
        if self.size_bytes is not None and (isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int) or self.size_bytes < 0):
            raise ContractValidationError("size_bytes must be a non-negative integer")
        object.__setattr__(self, "metadata", _metadata(self.metadata))

    @classmethod
    def from_payload(cls, value: Any) -> ResultArtifact:
        if isinstance(value, str):
            return cls(artifact_id=value)
        if not isinstance(value, Mapping):
            raise ContractValidationError("result artifact must be an ID or object")
        artifact_id = value.get("artifact_id") or value.get("id")
        known = {"artifact_id", "id", "name", "media_type", "size_bytes"}
        return cls(
            artifact_id=artifact_id,
            name=value.get("name"),
            media_type=value.get("media_type"),
            size_bytes=value.get("size_bytes"),
            metadata={key: item for key, item in value.items() if key not in known},
        )

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {"artifact_id": self.artifact_id}
        if self.name is not None:
            value["name"] = self.name
        if self.media_type is not None:
            value["media_type"] = self.media_type
        if self.size_bytes is not None:
            value["size_bytes"] = self.size_bytes
        value.update(_copy_mapping(self.metadata))
        return value


@dataclass(frozen=True)
class ResultEnvelope:
    """Normalized Judge result compatible with callback and polling responses."""

    evaluation_id: str
    status: str
    execution_id: str | None = None
    task_ref: str | None = None
    score: float | None = None
    metrics: Mapping[str, Any] = field(default_factory=dict)
    artifacts: tuple[ResultArtifact, ...] = ()
    failure_reason: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "evaluation_id", _required_text(self.evaluation_id, "evaluation_id"))
        object.__setattr__(self, "status", _required_text(self.status, "status"))
        object.__setattr__(self, "execution_id", _optional_text(self.execution_id, "execution_id"))
        object.__setattr__(self, "task_ref", _optional_text(self.task_ref, "task_ref"))
        if self.score is not None:
            object.__setattr__(self, "score", _finite_number(self.score, "score"))
        object.__setattr__(self, "metrics", _json_object(self.metrics, "metrics"))
        artifacts = tuple(
            artifact if isinstance(artifact, ResultArtifact) else ResultArtifact.from_payload(artifact)
            for artifact in self.artifacts
        )
        object.__setattr__(self, "artifacts", artifacts)
        if self.failure_reason is not None:
            if not isinstance(self.failure_reason, str) or not self.failure_reason.strip():
                raise ContractValidationError("failure_reason must not be empty")
            object.__setattr__(self, "failure_reason", self.failure_reason.strip())
        object.__setattr__(self, "metadata", _metadata(self.metadata))

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ResultEnvelope:
        if not isinstance(payload, Mapping):
            raise ContractValidationError("Judge result must be an object")
        evaluation_id = payload.get("evaluation_id") or payload.get("execution_id")
        artifact_values = payload.get("artifacts") or []
        if not isinstance(artifact_values, (list, tuple)):
            raise ContractValidationError("artifacts must be a list")
        known = {"evaluation_id", "execution_id", "status", "task_ref", "score", "metrics", "artifacts", "failure_reason", "metadata"}
        raw_metadata = payload.get("metadata") or {}
        if not isinstance(raw_metadata, Mapping):
            raise ContractValidationError("metadata must be an object")
        metadata = dict(raw_metadata)
        metadata.update({key: value for key, value in payload.items() if key not in known})
        return cls(
            evaluation_id=evaluation_id,
            execution_id=payload.get("execution_id"),
            status=payload.get("status"),
            task_ref=payload.get("task_ref"),
            score=payload.get("score"),
            metrics=payload.get("metrics") or {},
            artifacts=tuple(ResultArtifact.from_payload(value) for value in artifact_values),
            failure_reason=payload.get("failure_reason"),
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "evaluation_id": self.evaluation_id,
            "status": self.status,
            "metrics": _copy_mapping(self.metrics),
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "metadata": _copy_mapping(self.metadata),
        }
        for key, item in (("execution_id", self.execution_id), ("task_ref", self.task_ref), ("score", self.score), ("failure_reason", self.failure_reason)):
            if item is not None:
                value[key] = item
        return value


def normalize_result(payload: Mapping[str, Any]) -> ResultEnvelope:
    """Normalize a Judge polling or callback payload into a typed envelope."""
    return ResultEnvelope.from_payload(payload)
