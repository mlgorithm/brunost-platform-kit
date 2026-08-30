"""Framework-neutral judge gateway and adapter protocol.

The gateway is the only object a platform application needs to know about.  It
uses the standard library so it can be embedded in FastAPI, Django, Flask,
Starlette, Fastify, or a custom service without pulling a web framework into
the Platform Kit.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote, urlparse

from brunost_platform.artifacts import artifact_id, pack_directory
from brunost_platform.contracts import EvaluationRequest, ResultEnvelope, TaskRegistration, normalize_result
from brunost_platform.transport import (
    DEFAULT_MAX_ARTIFACT_RESPONSE_BYTES,
    DEFAULT_MAX_RESPONSE_BYTES,
    ResponseTooLarge,
    SafeHttpTransport,
)


class JudgeGatewayError(RuntimeError):
    """A judge request failed or returned an invalid response."""


class JudgeGateway(Protocol):
    def health(self) -> dict[str, Any]: ...

    def stats(self) -> dict[str, Any]: ...

    def list_tasks(self) -> list[dict[str, Any]]: ...

    def register_task(self, task: TaskRegistration | None = None, **kwargs: Any) -> dict[str, Any]: ...

    def list_workers(self) -> list[dict[str, Any]]: ...

    def drain_worker(self, worker_id: str, *, draining: bool = True) -> dict[str, Any]: ...

    def revoke_worker_credential(self, worker_id: str) -> dict[str, Any]: ...

    def list_executions(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]: ...

    def list_agents(self) -> list[dict[str, Any]]: ...

    def list_games(self) -> list[dict[str, Any]]: ...

    def register_agent(self, **kwargs: Any) -> dict[str, Any]: ...

    def register_game(self, **kwargs: Any) -> dict[str, Any]: ...

    def upload_artifact(self, path: str | Path) -> dict[str, Any]: ...

    def submit_evaluation(
        self,
        request: EvaluationRequest | None = None,
        *,
        task_ref: str | None = None,
        submission_artifact_id: str | None = None,
        idempotency_key: str | None = None,
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

    def get_evaluation_result(self, evaluation_id: str) -> ResultEnvelope: ...

    def cancel(self, evaluation_id: str) -> dict[str, Any]: ...


@dataclass
class HttpJudgeGateway:
    """Small HTTP adapter suitable for both a platform and a CLI."""

    base_url: str = "http://127.0.0.1:8787"
    token: str | None = None
    timeout: float = 30
    ca_file: str | Path | None = None
    client_cert_file: str | Path | None = None
    client_key_file: str | Path | None = None
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    max_artifact_response_bytes: int = DEFAULT_MAX_ARTIFACT_RESPONSE_BYTES
    require_https: bool | None = None

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("Judge URL must be an absolute HTTP(S) URL")
        production = os.environ.get("BRUNOST_PLATFORM_ENVIRONMENT", os.environ.get("ENVIRONMENT", "")).lower() in {
            "prod",
            "production",
            "staging",
        }
        if (production if self.require_https is None else self.require_https) and parsed.scheme != "https":
            raise ValueError("Judge URL must use HTTPS outside development")
        if self.timeout <= 0:
            raise ValueError("Judge timeout must be positive")
        self.base_url = self.base_url.rstrip("/")
        self._transport = SafeHttpTransport(
            ca_file=self.ca_file,
            client_cert_file=self.client_cert_file,
            client_key_file=self.client_key_file,
            max_response_bytes=self.max_response_bytes,
            max_artifact_response_bytes=self.max_artifact_response_bytes,
        )
        # When the canonical Judge SDK is installed, use it as the transport
        # implementation.  The small stdlib fallback below keeps the Kit
        # dependency-free and still works for framework integrations that only
        # install ``brunost-platform-kit``.
        self._sdk_client: Any | None = None
        try:
            from brunost_judge.sdk import JudgeClient

            self._sdk_client = JudgeClient(
                self.base_url,
                self.token,
                self.timeout,
                ca_file=self.ca_file,
                client_cert_file=self.client_cert_file,
                client_key_file=self.client_key_file,
                max_response_bytes=self.max_response_bytes,
                max_artifact_response_bytes=self.max_artifact_response_bytes,
            )
        except TypeError:
            # An older optional SDK can still be used by an application that
            # has not upgraded its Judge dependency yet.
            if any((self.ca_file, self.client_cert_file, self.client_key_file)):
                raise RuntimeError("installed Judge SDK does not support the configured TLS options")
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
        if path in {"/v1/executions", "/v1/evaluations"} and payload and payload.get("idempotency_key"):
            headers["Idempotency-Key"] = str(payload["idempotency_key"])
        request = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with self._transport.open(request, timeout=self.timeout) as response:
                decoded = json.loads(self._transport.read_json(response).decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                detail = self._transport.read(exc, max_bytes=64 * 1024).decode(errors="replace")
            except ResponseTooLarge:
                detail = "response body too large"
            raise JudgeGatewayError(f"judge API {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, ResponseTooLarge) as exc:
            raise JudgeGatewayError(f"judge API unavailable: {exc}") from exc
        if not isinstance(decoded, dict):
            raise JudgeGatewayError("judge API returned a non-object response")
        return decoded

    def health(self) -> dict[str, Any]:
        if self._sdk_client is not None:
            return self._sdk_client.health()
        return self._request("GET", "/healthz")

    def stats(self) -> dict[str, Any]:
        return self._request("GET", "/v1/stats")

    def list_tasks(self) -> list[dict[str, Any]]:
        return self._request("GET", "/v1/tasks")  # type: ignore[return-value]

    def register_task(self, task: TaskRegistration | None = None, **kwargs: Any) -> dict[str, Any]:
        """Register a task using a typed contract or the legacy keyword API.

        The keyword form is retained for existing integrations.  New callers
        should pass ``TaskRegistration`` so the artifact/path invariant and
        identifier validation happen before an HTTP request is made.
        """
        if task is not None:
            if kwargs:
                raise TypeError("pass either a TaskRegistration or keyword fields, not both")
            payload = task.to_payload()
        else:
            payload = kwargs
        return self._request("POST", "/v1/tasks", payload)

    def list_workers(self) -> list[dict[str, Any]]:
        return self._request("GET", "/v1/workers")  # type: ignore[return-value]

    def drain_worker(self, worker_id: str, *, draining: bool = True) -> dict[str, Any]:
        encoded_worker_id = quote(str(worker_id), safe="")
        value = "true" if draining else "false"
        return self._request("POST", f"/v1/workers/{encoded_worker_id}/drain?draining={value}")

    def revoke_worker_credential(self, worker_id: str) -> dict[str, Any]:
        encoded_worker_id = quote(str(worker_id), safe="")
        return self._request("POST", f"/v1/workers/{encoded_worker_id}/credential/revoke")

    def list_executions(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = f"?limit={max(1, min(limit, 500))}"
        if status:
            query += f"&status={status}"
        return self._request("GET", f"/v1/executions{query}")  # type: ignore[return-value]

    def list_agents(self) -> list[dict[str, Any]]:
        return self._request("GET", "/v1/agents")  # type: ignore[return-value]

    def list_games(self) -> list[dict[str, Any]]:
        return self._request("GET", "/v1/games")  # type: ignore[return-value]

    def register_agent(self, **kwargs: Any) -> dict[str, Any]:
        return self._request("POST", "/v1/agents", kwargs)

    def register_game(self, **kwargs: Any) -> dict[str, Any]:
        return self._request("POST", "/v1/games", kwargs)

    def _raw(self, method: str, path: str, data: bytes) -> bytes:
        headers = {"Accept": "application/octet-stream", "Content-Type": "application/gzip"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with self._transport.open(request, timeout=self.timeout) as response:
                return self._transport.read_json(response)
        except urllib.error.HTTPError as exc:
            try:
                detail = self._transport.read(exc, max_bytes=64 * 1024).decode(errors="replace")
            except ResponseTooLarge:
                detail = "response body too large"
            raise JudgeGatewayError(f"judge API {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, ResponseTooLarge) as exc:
            raise JudgeGatewayError(f"judge API unavailable: {exc}") from exc

    def upload_artifact(self, path: str | Path) -> dict[str, Any]:
        if self._sdk_client is not None:
            return self._sdk_client.upload_artifact(path)
        data = pack_directory(path)
        identifier = artifact_id(data)
        return json.loads(self._raw("PUT", f"/v1/artifacts/{identifier}", data).decode("utf-8"))

    def submit_evaluation(
        self,
        request: EvaluationRequest | None = None,
        *,
        task_ref: str | None = None,
        submission_artifact_id: str | None = None,
        idempotency_key: str | None = None,
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
        """Submit a typed evaluation request or preserve the legacy API.

        The legacy keyword form intentionally remains available for existing
        public integrations and is serialized exactly as before.  Typed
        callers get validation before transport; both forms use the same wire
        field names.
        """
        if request is not None:
            if any(value is not None for value in (task_ref, submission_artifact_id, idempotency_key)):
                raise TypeError("pass either an EvaluationRequest or keyword fields, not both")
            if (
                evaluation_kind != "batch"
                or agent_refs is not None
                or game_ref is not None
                or seed is not None
                or callback_url is not None
                or callback_token is not None
                or metadata is not None
                or queue != "default"
                or resource_class != "cpu"
                or priority != 0
            ):
                raise TypeError("pass either an EvaluationRequest or keyword fields, not both")
        else:
            if task_ref is None or submission_artifact_id is None or idempotency_key is None:
                raise TypeError("task_ref, submission_artifact_id, and idempotency_key are required")
            payload = {
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
            }
        if request is not None:
            payload = request.to_payload()
        if self._sdk_client is not None:
            return self._sdk_client.submit_evaluation(**payload)
        return self._request("POST", "/v1/evaluations", payload)

    def get_evaluation(self, evaluation_id: str) -> dict[str, Any]:
        if self._sdk_client is not None:
            return self._sdk_client.get_evaluation(evaluation_id)
        return self._request("GET", f"/v1/evaluations/{evaluation_id}")

    def get_evaluation_result(self, evaluation_id: str) -> ResultEnvelope:
        """Fetch and normalize a Judge result without exposing raw payloads."""
        return normalize_result(self.get_evaluation(evaluation_id))

    def cancel(self, evaluation_id: str) -> dict[str, Any]:
        if self._sdk_client is not None:
            return self._sdk_client.cancel(evaluation_id)
        return self._request("POST", f"/v1/executions/{evaluation_id}/cancel")


def gateway_from_environment() -> HttpJudgeGateway:
    """Build the default HTTP gateway without requiring a framework."""
    return HttpJudgeGateway(
        base_url=os.environ.get("BRUNOST_JUDGE_URL", "http://127.0.0.1:8787"),
        token=os.environ.get("BRUNOST_JUDGE_API_TOKEN"),
        ca_file=os.environ.get("BRUNOST_JUDGE_CA_FILE") or None,
        client_cert_file=os.environ.get("BRUNOST_JUDGE_CLIENT_CERT_FILE") or None,
        client_key_file=os.environ.get("BRUNOST_JUDGE_CLIENT_KEY_FILE") or None,
        max_response_bytes=int(os.environ.get("BRUNOST_JUDGE_MAX_RESPONSE_BYTES", str(DEFAULT_MAX_RESPONSE_BYTES))),
        max_artifact_response_bytes=int(
            os.environ.get("BRUNOST_JUDGE_MAX_ARTIFACT_RESPONSE_BYTES", str(DEFAULT_MAX_ARTIFACT_RESPONSE_BYTES))
        ),
        require_https=os.environ.get("BRUNOST_PLATFORM_REQUIRE_HTTPS", "").lower() == "true"
        if "BRUNOST_PLATFORM_REQUIRE_HTTPS" in os.environ
        else None,
    )
