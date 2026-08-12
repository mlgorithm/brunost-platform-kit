"""Small application service shared by generated platform templates."""

from __future__ import annotations

from typing import Any

from brunost_platform.adapters import LeaderboardAdapter, NullLeaderboard
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
        if self.store is not None:
            self.store.save_submission(submission)
        metadata = {
            "contestant_id": submission.contestant_id,
            "contest_id": submission.contest_id,
            **submission.metadata,
            **(options.pop("metadata", {}) or {}),
        }
        result = self.judge.submit_evaluation(
            task_ref=submission.task_ref,
            submission_path=submission.artifact_path,
            idempotency_key=submission.submission_id,
            evaluation_kind=evaluation_kind,
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
            metadata={"status": result.get("status"), "metrics": result.get("metrics", {})},
        )
        self.leaderboard.record(entry)
        return entry
