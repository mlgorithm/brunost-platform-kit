"""Framework-neutral judge gateway and adapter protocol.

The gateway is the only object a platform application needs to know about.  It
uses the standard library so it can be embedded in FastAPI, Django, Flask,
Starlette, Fastify, or a custom service without pulling a web framework into
the Platform Kit.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from brunost_platform.artifacts import artifact_id, pack_directory


class JudgeGatewayError(RuntimeError):
    """A judge request failed or returned an invalid response."""


class JudgeGateway(Protocol):
    def health(self) -> dict[str, Any]: ...

    def upload_artifact(self, path: str | Path) -> dict[str, Any]: ...

    def submit_evaluation(
        self,
        *,
        task_ref: str,
        submission_artifact_id: str,
        idempotency_key: str,
        evaluation_kind: str = "batch",
        agent_refs: list[str] | None = None,
        game_ref: str | None = None,
        seed: int | None = None,
        callback_url: str | None = None,
        callback_token: str | None = None,
        metadata: dict[str, Any] | None = None,
        queue: str = "default",
        resource_class: str = "cpu",
        priority: int = 0,
    ) -> dict[str, Any]: ...

    def get_evaluation(self, evaluation_id: str) -> dict[str, Any]: ...

    def cancel(self, evaluation_id: str) -> dict[str, Any]: ...


@dataclass
class HttpJudgeGateway:
    """Small HTTP adapter suitable for both a platform and a CLI."""

    base_url: str = "http://127.0.0.1:8787"
    token: str | None = None
    timeout: float = 30

    def __post_init__(self) -> None:
        # When the canonical Judge SDK is installed, use it as the transport
        # implementation.  The small stdlib fallback below keeps the Kit
        # dependency-free and still works for framework integrations that only
        # install ``brunost-platform-kit``.
        self._sdk_client: Any | None = None
        try:
            from brunost_judge.sdk import JudgeClient

            self._sdk_client = JudgeClient(self.base_url, self.token, self.timeout)
        except ImportError:
            self._sdk_client = None

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(self.base_url.rstrip("/") + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                decoded = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise JudgeGatewayError(f"judge API {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise JudgeGatewayError(f"judge API unavailable: {exc}") from exc
        if not isinstance(decoded, dict):
            raise JudgeGatewayError("judge API returned a non-object response")
        return decoded

    def health(self) -> dict[str, Any]:
        if self._sdk_client is not None:
            return self._sdk_client.health()
        return self._request("GET", "/healthz")

    def _raw(self, method: str, path: str, data: bytes) -> bytes:
        headers = {"Accept": "application/octet-stream", "Content-Type": "application/gzip"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(self.base_url.rstrip("/") + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            raise JudgeGatewayError(f"judge API {exc.code}: {exc.read().decode(errors='replace')}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise JudgeGatewayError(f"judge API unavailable: {exc}") from exc

    def upload_artifact(self, path: str | Path) -> dict[str, Any]:
        if self._sdk_client is not None:
            return self._sdk_client.upload_artifact(path)
        data = pack_directory(path)
        identifier = artifact_id(data)
        return json.loads(self._raw("PUT", f"/v1/artifacts/{identifier}", data).decode("utf-8"))

    def submit_evaluation(
        self,
        *,
        task_ref: str,
        submission_artifact_id: str,
        idempotency_key: str,
        evaluation_kind: str = "batch",
        agent_refs: list[str] | None = None,
        game_ref: str | None = None,
        seed: int | None = None,
        callback_url: str | None = None,
        callback_token: str | None = None,
        metadata: dict[str, Any] | None = None,
        queue: str = "default",
        resource_class: str = "cpu",
        priority: int = 0,
    ) -> dict[str, Any]:
        if self._sdk_client is not None:
            return self._sdk_client.submit_evaluation(
                task_ref=task_ref,
                submission_artifact_id=submission_artifact_id,
                idempotency_key=idempotency_key,
                evaluation_kind=evaluation_kind,
                agent_refs=agent_refs or [],
                game_ref=game_ref,
                seed=seed,
                callback_url=callback_url,
                callback_token=callback_token,
                metadata=metadata or {},
                queue=queue,
                resource_class=resource_class,
                priority=priority,
            )
        return self._request("POST", "/v1/evaluations", {
            "task_ref": task_ref,
            "submission_artifact_id": submission_artifact_id,
            "idempotency_key": idempotency_key,
            "evaluation_kind": evaluation_kind,
            "agent_refs": agent_refs or [],
            "game_ref": game_ref,
            "seed": seed,
            "callback_url": callback_url,
            "callback_token": callback_token,
            "metadata": metadata or {},
            "queue": queue,
            "resource_class": resource_class,
            "priority": priority,
        })

    def get_evaluation(self, evaluation_id: str) -> dict[str, Any]:
        if self._sdk_client is not None:
            return self._sdk_client.get_evaluation(evaluation_id)
        return self._request("GET", f"/v1/evaluations/{evaluation_id}")

    def cancel(self, evaluation_id: str) -> dict[str, Any]:
        if self._sdk_client is not None:
            return self._sdk_client.cancel(evaluation_id)
        return self._request("POST", f"/v1/executions/{evaluation_id}/cancel")


def gateway_from_environment() -> HttpJudgeGateway:
    """Build the default HTTP gateway without requiring a framework."""
    import os

    return HttpJudgeGateway(
        base_url=os.environ.get("BRUNOST_JUDGE_URL", "http://127.0.0.1:8787"),
        token=os.environ.get("BRUNOST_JUDGE_API_TOKEN"),
    )
