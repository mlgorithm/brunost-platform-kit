"""Small application service shared by generated platform templates."""

from __future__ import annotations

import hmac
import json
import os
from typing import Any

from brunost_platform.adapters import LeaderboardAdapter, NullLeaderboard
from brunost_platform.callbacks import verify_judge_callback
from brunost_platform.gateway import JudgeGateway
from brunost_platform.models import Contest, LeaderboardEntry, Submission
from brunost_platform.store import SQLitePlatformStore


class PlatformApplication:
    """Compose a judge gateway with optional platform-owned modules."""

    def __init__(self, judge: JudgeGateway, leaderboard: LeaderboardAdapter | None = None, store: SQLitePlatformStore | None = None) -> None:
        self.judge = judge
        self.store = store
        self.leaderboard = leaderboard or (store if store is not None else NullLeaderboard())

    def create_contest(self, contest: Contest) -> Contest:
        if self.store is None:
            raise RuntimeError("a persistent store is required to create contests")
        return self.store.create_contest(contest)

    def submit(self, submission: Submission, *, evaluation_kind: str = "batch", **options: Any) -> dict[str, Any]:
        if evaluation_kind in {"agent", "match"}:
            raise NotImplementedError(
                f"evaluation kind '{evaluation_kind}' requires an installed agent/game runner plugin"
            )
        if self.store is not None:
            self.store.save_submission(submission)
        if self.store is None:
            raise RuntimeError("a persistent store is required for immutable submissions")
        metadata = {
            "platform_submission_id": submission.submission_id,
            "contestant_id": submission.contestant_id,
            "contest_id": submission.contest_id,
            **submission.metadata,
            **(options.pop("metadata", {}) or {}),
        }
        artifact = self.judge.upload_artifact(submission.artifact_path)
        callback_url = options.pop("callback_url", None) or os.environ.get("BRUNOST_PLATFORM_CALLBACK_URL")
        callback_token = options.pop("callback_token", None) or os.environ.get("BRUNOST_PLATFORM_CALLBACK_TOKEN")
        result = self.judge.submit_evaluation(
            task_ref=submission.task_ref,
            submission_artifact_id=str(artifact["artifact_id"]),
            idempotency_key=submission.submission_id,
            evaluation_kind=evaluation_kind,
            callback_url=callback_url,
            callback_token=callback_token,
            metadata=metadata,
            **options,
        )
        evaluation_id = str(result.get("evaluation_id") or result.get("execution_id"))
        if submission.contest_id:
            self.leaderboard.record(LeaderboardEntry(
                contestant_id=submission.contestant_id,
                contest_id=submission.contest_id,
                task_ref=submission.task_ref,
                score=result.get("score"),
                evaluation_id=evaluation_id,
                visible=False,
            ))
        return result

    def cancel(self, evaluation_id: str) -> dict[str, Any]:
        return self.judge.cancel(evaluation_id)

    def handle_callback(self, body: bytes, headers: dict[str, str], *, secret: str | None = None) -> dict[str, Any]:
        """Verify, deduplicate, and project one Judge callback automatically."""
        if self.store is None:
            raise RuntimeError("a persistent store is required for callback receipts")
        expected_token = os.environ.get("BRUNOST_PLATFORM_CALLBACK_TOKEN")
        if expected_token:
            authorization = next((value for key, value in headers.items() if key.lower() == "authorization"), "")
            if not hmac.compare_digest(authorization, f"Bearer {expected_token}"):
                raise ValueError("invalid callback bearer token")
        event_id = verify_judge_callback(body, headers, secret or os.environ.get("BRUNOST_JUDGE_CALLBACK_SECRET", ""))
        if not event_id:
            raise ValueError("invalid or stale Judge callback signature")
        payload = json.loads(body.decode("utf-8"))
        metadata = payload.get("metadata") or {}
        submission_id = metadata.get("platform_submission_id")
        if not submission_id:
            raise ValueError("callback is missing metadata.platform_submission_id")
        submission = self.store.get_submission(str(submission_id))
        if submission is None:
            raise KeyError(f"unknown submission: {submission_id}")
        if not self.store.accept_callback_event(event_id):
            return {"status": "duplicate", "event_id": event_id, "submission_id": submission_id}
        visible = bool((self.store.get_contest(submission.contest_id).metadata if submission.contest_id and self.store.get_contest(submission.contest_id) else {}).get("leaderboard_visible", False))
        self.record_result(submission, payload, visible=visible)
        self.store.update_submission_result(submission.submission_id, payload)
        return {"status": payload.get("status", "received"), "event_id": event_id, "submission_id": submission_id}

    def record_result(self, submission: Submission, result: dict[str, Any], *, visible: bool = False) -> LeaderboardEntry | None:
        """Project a judge result into the platform-owned leaderboard."""
        if not submission.contest_id:
            return None
        entry = LeaderboardEntry(
            contestant_id=submission.contestant_id,
            contest_id=submission.contest_id,
            task_ref=submission.task_ref,
            score=result.get("score"),
            evaluation_id=str(result.get("evaluation_id") or result.get("execution_id")),
            visible=visible,
            metadata={
                "status": result.get("status"),
                "metrics": result.get("metrics", {}),
                **{key: result[key] for key in ("task_digest", "evaluator", "runtime_image", "seed", "event_id") if key in result},
            },
        )
        self.leaderboard.record(entry)
        return entry
