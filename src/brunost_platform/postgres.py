"""Small PostgreSQL-backed Platform Kit store for multi-instance deployments.

SQLite remains the reference/local store.  Production Platform Core instances
need shared transactional state, so this adapter keeps the same domain
contract in one JSONB state document protected by a PostgreSQL row lock.  The
document format is deliberately internal; callers continue using the typed
models and can migrate to normalized tables later without changing the
platform application contract.
"""

from __future__ import annotations

import copy
import hashlib
import secrets
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, TypeVar

from brunost_platform.leaderboard_policy import project_leaderboard
from brunost_platform.models import Contest, LeaderboardEntry, Submission, User, WorkerOperation

_T = TypeVar("_T")


class PostgresPlatformStore:
    """Transactional shared store for Premium/Core production deployments."""

    def __init__(self, database: str) -> None:
        if not database.strip().startswith(("postgres://", "postgresql://")):
            raise ValueError("PostgresPlatformStore requires a PostgreSQL DSN")
        try:
            import psycopg
            from psycopg.rows import dict_row
            from psycopg.types.json import Jsonb
        except ImportError as exc:  # pragma: no cover - exercised in production images
            raise RuntimeError("install the platform-kit postgres extra to use PostgreSQL storage") from exc
        self.database = database.strip()
        self._connect_factory = psycopg.connect
        self._dict_row = dict_row
        self._Jsonb = Jsonb
        self._initialize()

    def _connect(self):
        return self._connect_factory(self.database, row_factory=self._dict_row)

    @staticmethod
    def _empty_state() -> dict[str, Any]:
        return {
            "users": {},
            "contests": {},
            "submissions": {},
            "leaderboard": {},
            "callback_events": {},
            "sessions": {},
            "registrations": {},
            "leaderboard_history": [],
            "worker_operations": [],
        }

    def _initialize(self) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS brunost_platform_state (
                    state_id SMALLINT PRIMARY KEY CHECK (state_id = 1),
                    state_json JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cursor.execute(
                """
                INSERT INTO brunost_platform_state(state_id, state_json)
                VALUES (1, %s)
                ON CONFLICT (state_id) DO NOTHING
                """,
                (self._Jsonb(self._empty_state()),),
            )

    def ping(self) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT 1")

    def _read_state(self) -> dict[str, Any]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT state_json FROM brunost_platform_state WHERE state_id = 1")
            row = cursor.fetchone()
        if row is None:
            raise RuntimeError("Platform Core state row is missing")
        return copy.deepcopy(row["state_json"])

    def _update_state(self, mutate: Callable[[dict[str, Any]], _T]) -> _T:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT state_json FROM brunost_platform_state WHERE state_id = 1 FOR UPDATE")
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("Platform Core state row is missing")
            state = copy.deepcopy(row["state_json"])
            result = mutate(state)
            cursor.execute(
                "UPDATE brunost_platform_state SET state_json = %s, updated_at = now() WHERE state_id = 1",
                (self._Jsonb(state),),
            )
            return result

    @staticmethod
    def _user(row: dict[str, Any]) -> User:
        return User(
            row["user_id"],
            row["email"],
            row["display_name"],
            row.get("organization_id"),
            tuple(row.get("roles", [])),
            dict(row.get("metadata", {})),
            row.get("password_hash"),
        )

    @staticmethod
    def _contest(row: dict[str, Any]) -> Contest:
        return Contest(row["contest_id"], row["name"], tuple(row.get("task_refs", [])), row.get("status", "draft"), dict(row.get("metadata", {})))

    @staticmethod
    def _submission(row: dict[str, Any]) -> Submission:
        return Submission(row["submission_id"], row["contestant_id"], row["task_ref"], row["artifact_path"], row.get("contest_id"), dict(row.get("metadata", {})))

    @staticmethod
    def _entry(row: dict[str, Any]) -> LeaderboardEntry:
        return LeaderboardEntry(row["contestant_id"], row["contest_id"], row["task_ref"], row.get("score"), row["evaluation_id"], bool(row.get("visible", True)), dict(row.get("metadata", {})))

    def save_user(self, user: User) -> User:
        def mutate(state: dict[str, Any]) -> None:
            previous = state["users"].get(user.user_id, {})
            payload = user.as_dict()
            if user.password_hash is None and previous.get("password_hash"):
                payload["password_hash"] = previous["password_hash"]
            state["users"][user.user_id] = payload

        self._update_state(mutate)
        return user

    def get_user(self, user_id: str) -> User | None:
        row = self._read_state()["users"].get(user_id)
        return self._user(row) if row else None

    def get_user_by_email(self, email: str) -> User | None:
        normalized = email.strip().lower()
        for row in self._read_state()["users"].values():
            if row["email"] == normalized:
                return self._user(row)
        return None

    def list_users(self) -> list[User]:
        rows = sorted(self._read_state()["users"].values(), key=lambda row: row["email"])
        return [self._user(row) for row in rows]

    def create_session(self, user_id: str, *, ttl_seconds: int = 86400) -> str:
        token = secrets.token_urlsafe(32)
        token_hash = self._token_hash(token)
        self._update_state(lambda state: state["sessions"].__setitem__(token_hash, {"user_id": user_id, "expires_at": int(time.time()) + ttl_seconds}))
        return token

    def get_session_user(self, token: str) -> User | None:
        session = self._read_state()["sessions"].get(self._token_hash(token))
        if not session or int(session["expires_at"]) <= int(time.time()):
            return None
        return self.get_user(session["user_id"])

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def create_contest(self, contest: Contest) -> Contest:
        self._update_state(lambda state: state["contests"].__setitem__(contest.contest_id, contest.as_dict()))
        return contest

    def get_contest(self, contest_id: str) -> Contest | None:
        row = self._read_state()["contests"].get(contest_id)
        return self._contest(row) if row else None

    def register_contestant(self, contest_id: str, user_id: str) -> None:
        self._update_state(lambda state: state["registrations"].setdefault(f"{contest_id}:{user_id}", datetime.now(UTC).isoformat()))

    def is_registered(self, contest_id: str, user_id: str) -> bool:
        return f"{contest_id}:{user_id}" in self._read_state()["registrations"]

    def list_contests(self) -> list[Contest]:
        rows = sorted(self._read_state()["contests"].values(), key=lambda row: row["contest_id"])
        return [self._contest(row) for row in rows]

    def save_submission(self, submission: Submission) -> Submission:
        def mutate(state: dict[str, Any]) -> None:
            previous = state["submissions"].get(submission.submission_id, {})
            payload = submission.as_dict()
            if not payload.get("metadata") and previous.get("metadata"):
                payload["metadata"] = previous["metadata"]
            state["submissions"][submission.submission_id] = payload

        self._update_state(mutate)
        return submission

    def list_submissions(self, *, contestant_id: str | None = None, contest_id: str | None = None) -> list[Submission]:
        rows = self._read_state()["submissions"].values()
        if contestant_id:
            rows = (row for row in rows if row["contestant_id"] == contestant_id)
        if contest_id:
            rows = (row for row in rows if row.get("contest_id") == contest_id)
        return [self._submission(row) for row in sorted(rows, key=lambda row: row["submission_id"], reverse=True)]

    def update_submission_result(self, submission_id: str, result: dict[str, Any]) -> None:
        def mutate(state: dict[str, Any]) -> None:
            row = state["submissions"].get(submission_id)
            if row is None:
                raise KeyError(f"unknown submission: {submission_id}")
            row["metadata"] = {**row.get("metadata", {}), "result": result}

        self._update_state(mutate)

    def get_submission(self, submission_id: str) -> Submission | None:
        row = self._read_state()["submissions"].get(submission_id)
        return self._submission(row) if row else None

    def record_leaderboard(self, entry: LeaderboardEntry) -> LeaderboardEntry:
        metadata = {**entry.metadata, "recorded_at": datetime.now(UTC).isoformat()}
        entry = LeaderboardEntry(entry.contestant_id, entry.contest_id, entry.task_ref, entry.score, entry.evaluation_id, entry.visible, metadata)

        def mutate(state: dict[str, Any]) -> None:
            state["leaderboard"][entry.evaluation_id] = entry.as_dict()
            state["leaderboard_history"].append({"revision_id": secrets.token_hex(16), **entry.as_dict()})

        self._update_state(mutate)
        return entry

    def record(self, entry: LeaderboardEntry) -> None:
        self.record_leaderboard(entry)

    def accept_callback_event(self, event_id: str) -> bool:
        if not event_id.strip():
            raise ValueError("event_id is required")

        def mutate(state: dict[str, Any]) -> bool:
            if event_id in state["callback_events"]:
                return False
            now = datetime.now(UTC).isoformat()
            state["callback_events"][event_id] = {"received_at": now, "updated_at": now, "status": "applied", "attempts": 0}
            return True

        return self._update_state(mutate)

    def claim_callback_event(self, event_id: str, *, submission_id: str, payload: dict[str, Any], stale_seconds: int = 900) -> str:
        def mutate(state: dict[str, Any]) -> str:
            now = datetime.now(UTC)
            row = state["callback_events"].get(event_id)
            if row is None:
                state["callback_events"][event_id] = {"received_at": now.isoformat(), "updated_at": now.isoformat(), "status": "applying", "submission_id": submission_id, "payload": payload, "attempts": 1}
                return "claimed"
            if row.get("status") == "applied":
                return "duplicate"
            try:
                updated = datetime.fromisoformat(str(row.get("updated_at", "")))
                if updated.tzinfo is None:
                    updated = updated.replace(tzinfo=UTC)
                stale = (now - updated).total_seconds() > stale_seconds
            except ValueError:
                stale = True
            if row.get("status") == "applying" and not stale:
                return "duplicate"
            row.update({"status": "applying", "submission_id": submission_id, "payload": payload, "attempts": int(row.get("attempts", 0)) + 1, "last_error": None, "updated_at": now.isoformat()})
            return "claimed"

        return self._update_state(mutate)

    def mark_callback_applied(self, event_id: str) -> None:
        self._update_state(lambda state: state["callback_events"].get(event_id, {}).update({"status": "applied", "last_error": None, "updated_at": datetime.now(UTC).isoformat()}))

    def mark_callback_failed(self, event_id: str, exc: Exception) -> None:
        self._update_state(lambda state: state["callback_events"].get(event_id, {}).update({"status": "failed", "last_error": str(exc)[:2000], "updated_at": datetime.now(UTC).isoformat()}))

    def apply_callback_projection(self, *, event_id: str, submission: Submission, payload: dict[str, Any], entry: LeaderboardEntry) -> None:
        def mutate(state: dict[str, Any]) -> None:
            current = state["submissions"].get(submission.submission_id)
            if current is None:
                raise KeyError(f"unknown submission: {submission.submission_id}")
            current["metadata"] = {**current.get("metadata", {}), "result": payload}
            metadata = {**entry.metadata, "recorded_at": datetime.now(UTC).isoformat()}
            stored = LeaderboardEntry(entry.contestant_id, entry.contest_id, entry.task_ref, entry.score, entry.evaluation_id, entry.visible, metadata)
            state["leaderboard"][stored.evaluation_id] = stored.as_dict()
            state["leaderboard_history"].append({"revision_id": secrets.token_hex(16), **stored.as_dict()})
            state["callback_events"].setdefault(event_id, {})
            state["callback_events"][event_id].update({"status": "applied", "last_error": None, "updated_at": datetime.now(UTC).isoformat()})

        self._update_state(mutate)

    def list_leaderboard(self, contest_id: str, *, visible_only: bool = True) -> list[LeaderboardEntry]:
        state = self._read_state()
        rows = [row for row in state["leaderboard"].values() if row["contest_id"] == contest_id and (not visible_only or row.get("visible", True))]
        entries = [self._entry(row) for row in rows]
        contest = state["contests"].get(contest_id)
        return project_leaderboard(entries, dict(contest.get("metadata", {})) if contest else {}, visible_only=visible_only)

    def leaderboard_history(self, contest_id: str) -> list[dict[str, Any]]:
        return [row for row in self._read_state()["leaderboard_history"] if row["contest_id"] == contest_id]

    def record_worker_operation(self, operation: WorkerOperation) -> WorkerOperation:
        def mutate(state: dict[str, Any]) -> None:
            operations = state.setdefault("worker_operations", [])
            payload = operation.as_dict()
            for index, current in enumerate(operations):
                if current.get("operation_id") == operation.operation_id:
                    operations[index] = payload
                    break
            else:
                operations.append(payload)

        self._update_state(mutate)
        return operation

    def list_worker_operations(self, *, worker_id: str | None = None, limit: int = 50) -> list[WorkerOperation]:
        rows = self._read_state().get("worker_operations", [])
        if worker_id:
            rows = [row for row in rows if row.get("worker_id") == worker_id]
        rows = sorted(rows, key=lambda row: str(row.get("requested_at", "")), reverse=True)[: max(1, min(int(limit), 200))]
        return [WorkerOperation(**row) for row in rows]
