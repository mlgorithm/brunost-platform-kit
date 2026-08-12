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
from typing import Any, Protocol


class JudgeGatewayError(RuntimeError):
    """A judge request failed or returned an invalid response."""


class JudgeGateway(Protocol):
    def health(self) -> dict[str, Any]: ...

    def submit_evaluation(
        self,
        *,
        task_ref: str,
        submission_path: str,
        idempotency_key: str,
        evaluation_kind: str = "batch",
        agent_refs: list[str] | None = None,
        game_ref: str | None = None,
        seed: int | None = None,
        metadata: dict[str, Any] | None = None,
        queue: str = "default",
        resource_class: str = "cpu",
        priority: int = 0,
    ) -> dict[str, Any]: ...

    def get_evaluation(self, evaluation_id: str) -> dict[str, Any]: ...


@dataclass
class HttpJudgeGateway:
    """Small HTTP adapter suitable for both a platform and a CLI."""

    base_url: str = "http://127.0.0.1:8787"
    token: str | None = None
    timeout: float = 30

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
        return self._request("GET", "/healthz")

    def submit_evaluation(
        self,
        *,
        task_ref: str,
        submission_path: str,
        idempotency_key: str,
        evaluation_kind: str = "batch",
        agent_refs: list[str] | None = None,
        game_ref: str | None = None,
        seed: int | None = None,
        metadata: dict[str, Any] | None = None,
        queue: str = "default",
        resource_class: str = "cpu",
        priority: int = 0,
    ) -> dict[str, Any]:
        return self._request("POST", "/v1/evaluations", {
            "task_ref": task_ref,
            "submission_path": submission_path,
            "idempotency_key": idempotency_key,
            "evaluation_kind": evaluation_kind,
            "agent_refs": agent_refs or [],
            "game_ref": game_ref,
            "seed": seed,
            "metadata": metadata or {},
            "queue": queue,
            "resource_class": resource_class,
            "priority": priority,
        })

    def get_evaluation(self, evaluation_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/evaluations/{evaluation_id}")


def gateway_from_environment() -> HttpJudgeGateway:
    """Build the default HTTP gateway without requiring a framework."""
    import os

    return HttpJudgeGateway(
        base_url=os.environ.get("BRUNOST_JUDGE_URL", "http://127.0.0.1:8787"),
        token=os.environ.get("BRUNOST_JUDGE_API_TOKEN"),
    )
