"""Versioned, framework-neutral leaderboard projection rules.

Contest applications store this policy in their own database.  The helper keeps
the reference SQLite store, generated FastAPI app, and Django adapter aligned
on aggregation and rank semantics without making the Judge aware of contests.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from brunost_platform.models import LeaderboardEntry

POLICY_VERSION = 1
_MISSING = object()


@dataclass(frozen=True)
class LeaderboardPolicy:
    version: int = POLICY_VERSION
    aggregation: str = "best_attempt"
    direction: str = "maximize"
    tie_policy: str = "standard"
    visible: bool = False
    freeze_at: str | None = None
    reveal_at: str | None = None


def normalize_policy(metadata: dict[str, Any] | None) -> LeaderboardPolicy:
    source = metadata or {}
    nested = source.get("leaderboard_policy")
    values = nested if isinstance(nested, dict) else source
    aggregation = str(values.get("aggregation") or ("best_attempt" if values.get("best_attempt", True) else "all_attempts"))
    if aggregation not in {"best_attempt", "sum", "average", "max", "all_attempts"}:
        aggregation = "best_attempt"
    direction = str(values.get("direction") or "maximize").lower()
    if direction not in {"maximize", "minimize"}:
        direction = "maximize"
    tie_policy = str(values.get("tie_policy") or values.get("tie_breaker") or "standard").lower()
    if tie_policy not in {"standard", "dense", "ordinal"}:
        tie_policy = "standard"
    version = int(values.get("version") or POLICY_VERSION)
    if version != POLICY_VERSION:
        raise ValueError(f"unsupported leaderboard policy version: {version}")
    return LeaderboardPolicy(
        version=version,
        aggregation=aggregation,
        direction=direction,
        tie_policy=tie_policy,
        visible=bool(values.get("leaderboard_visible", values.get("visible", False))),
        freeze_at=values.get("freeze_at") if isinstance(values.get("freeze_at"), str) else None,
        reveal_at=values.get("reveal_at") if isinstance(values.get("reveal_at"), str) else None,
    )


def _instant(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _eligible(entries: Iterable[LeaderboardEntry], policy: LeaderboardPolicy, *, visible_only: bool, now: datetime) -> list[LeaderboardEntry]:
    rows = [entry for entry in entries if (entry.visible or not visible_only)]
    reveal_at = _instant(policy.reveal_at)
    if visible_only and reveal_at and now < reveal_at:
        return []
    freeze_at = _instant(policy.freeze_at)
    if visible_only and freeze_at and now >= freeze_at:
        frozen: list[LeaderboardEntry] = []
        for entry in rows:
            recorded = _instant(entry.metadata.get("recorded_at"))
            if recorded is None or recorded <= freeze_at:
                frozen.append(entry)
        rows = frozen
    return rows


def _better(left: float | None, right: float | None, direction: str) -> bool:
    if left is None:
        return False
    if right is None:
        return True
    return left > right if direction == "maximize" else left < right


def project_leaderboard(
    entries: Iterable[LeaderboardEntry],
    metadata: dict[str, Any] | None,
    *,
    visible_only: bool = True,
    now: datetime | None = None,
) -> list[LeaderboardEntry]:
    """Apply aggregation, visibility, and deterministic rank policy."""
    policy = normalize_policy(metadata)
    rows = _eligible(entries, policy, visible_only=visible_only, now=now or datetime.now(UTC))
    if policy.aggregation in {"best_attempt", "sum", "average", "max"}:
        best: dict[tuple[str, str], LeaderboardEntry] = {}
        for entry in rows:
            key = (entry.contestant_id, entry.task_ref)
            if key not in best or _better(entry.score, best[key].score, policy.direction):
                best[key] = entry
        rows = list(best.values())

    if policy.aggregation in {"sum", "average", "max"}:
        grouped: dict[str, list[LeaderboardEntry]] = {}
        for entry in rows:
            grouped.setdefault(entry.contestant_id, []).append(entry)
        aggregated: list[LeaderboardEntry] = []
        for contestant_id, contestant_rows in grouped.items():
            scores = [entry.score for entry in contestant_rows if entry.score is not None]
            if not scores:
                score = None
            elif policy.aggregation == "average":
                score = sum(scores) / len(scores)
            elif policy.aggregation == "max":
                score = max(scores) if policy.direction == "maximize" else min(scores)
            else:
                score = sum(scores)
            first = contestant_rows[0]
            aggregated.append(LeaderboardEntry(
                contestant_id=contestant_id,
                contest_id=first.contest_id,
                task_ref="__total__",
                score=score,
                evaluation_id=first.evaluation_id,
                visible=all(row.visible for row in contestant_rows),
                metadata={
                    "task_scores": {row.task_ref: row.score for row in contestant_rows},
                    "recorded_at": max(
                        (row.metadata.get("recorded_at", "") for row in contestant_rows),
                        default="",
                    ),
                },
            ))
        rows = aggregated
    elif policy.aggregation == "all_attempts":
        rows = list(rows)

    reverse = policy.direction == "maximize"
    rows.sort(key=lambda row: (row.score is None, -(row.score or 0) if reverse else (row.score or 0), row.contestant_id, row.task_ref))
    ranked: list[LeaderboardEntry] = []
    previous: float | None | object = _MISSING
    rank = 0
    for index, entry in enumerate(rows, start=1):
        if entry.score != previous:
            rank = index if policy.tie_policy != "dense" else rank + 1
            previous = entry.score
        elif policy.tie_policy == "ordinal":
            rank = index
        ranked.append(LeaderboardEntry(
            entry.contestant_id,
            entry.contest_id,
            entry.task_ref,
            entry.score,
            entry.evaluation_id,
            entry.visible,
            {**entry.metadata, "rank": rank, "policy_version": policy.version, "aggregation": policy.aggregation, "tie_policy": policy.tie_policy},
        ))
    return ranked
