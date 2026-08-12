"""Reference SQLite persistence for standalone Platform Kit deployments."""

from __future__ import annotations

import json
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any

from brunost_platform.models import Contest, LeaderboardEntry, Submission, User


class SQLitePlatformStore:
    """Small durable store that can later be replaced by an ORM adapter."""

    def __init__(self, database: str | Path = "platform.db") -> None:
        self.path = str(database)
        if self.path != ":memory:":
            Path(self.path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL,
                    organization_id TEXT, roles_json TEXT NOT NULL, metadata_json TEXT NOT NULL,
                    password_hash TEXT
                );
                CREATE TABLE IF NOT EXISTS contests (
                    contest_id TEXT PRIMARY KEY, name TEXT NOT NULL, task_refs_json TEXT NOT NULL,
                    status TEXT NOT NULL, metadata_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS submissions (
                    submission_id TEXT PRIMARY KEY, contestant_id TEXT NOT NULL, task_ref TEXT NOT NULL,
                    artifact_path TEXT NOT NULL, contest_id TEXT, metadata_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS leaderboard (
                    evaluation_id TEXT PRIMARY KEY, contestant_id TEXT NOT NULL, contest_id TEXT NOT NULL,
                    task_ref TEXT NOT NULL, score REAL, visible INTEGER NOT NULL, metadata_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_leaderboard_contest ON leaderboard(contest_id, visible, score DESC);
                CREATE TABLE IF NOT EXISTS callback_events (
                    event_id TEXT PRIMARY KEY, received_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS contest_registrations (
                    contest_id TEXT NOT NULL, user_id TEXT NOT NULL, registered_at TEXT NOT NULL,
                    PRIMARY KEY(contest_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS leaderboard_history (
                    revision_id TEXT PRIMARY KEY, evaluation_id TEXT NOT NULL, contest_id TEXT NOT NULL,
                    contestant_id TEXT NOT NULL, task_ref TEXT NOT NULL, score REAL, recorded_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                """
            )
            columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
            if "password_hash" not in columns:
                db.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")

    def save_user(self, user: User) -> User:
        with self._connect() as db:
            db.execute(
                """INSERT INTO users(user_id,email,display_name,organization_id,roles_json,metadata_json,password_hash)
                   VALUES(?,?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET email=excluded.email,
                   display_name=excluded.display_name,organization_id=excluded.organization_id,
                   roles_json=excluded.roles_json,metadata_json=excluded.metadata_json,
                   password_hash=COALESCE(excluded.password_hash,users.password_hash)""",
                (user.user_id, user.email, user.display_name, user.organization_id, json.dumps(list(user.roles)), json.dumps(user.metadata, sort_keys=True), user.password_hash),
            )
        return user

    def get_user(self, user_id: str) -> User | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        if row is None:
            return None
        return User(row["user_id"], row["email"], row["display_name"], row["organization_id"], tuple(json.loads(row["roles_json"])), json.loads(row["metadata_json"]), row["password_hash"])

    def get_user_by_email(self, email: str) -> User | None:
        with self._connect() as db:
            row = db.execute("SELECT user_id FROM users WHERE email=?", (email.strip().lower(),)).fetchone()
        return self.get_user(row["user_id"]) if row else None

    def list_users(self) -> list[User]:
        """Return users in stable order for bootstrap and administration flows."""
        with self._connect() as db:
            rows = db.execute("SELECT user_id FROM users ORDER BY email").fetchall()
        return [self.get_user(row["user_id"]) for row in rows]  # type: ignore[misc]

    def create_session(self, user_id: str, *, ttl_seconds: int = 86400) -> str:
        token = secrets.token_urlsafe(32)
        with self._connect() as db:
            db.execute("INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(?,?,?)", (self._token_hash(token), user_id, int(time.time()) + ttl_seconds))
        return token

    def get_session_user(self, token: str) -> User | None:
        with self._connect() as db:
            row = db.execute("SELECT user_id FROM sessions WHERE token_hash=? AND expires_at>?", (self._token_hash(token), int(time.time()))).fetchone()
        return self.get_user(row["user_id"]) if row else None

    @staticmethod
    def _token_hash(token: str) -> str:
        import hashlib
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def create_contest(self, contest: Contest) -> Contest:
        with self._connect() as db:
            db.execute(
                """INSERT INTO contests(contest_id,name,task_refs_json,status,metadata_json) VALUES(?,?,?,?,?)
                   ON CONFLICT(contest_id) DO UPDATE SET name=excluded.name,task_refs_json=excluded.task_refs_json,
                   status=excluded.status,metadata_json=excluded.metadata_json""",
                (contest.contest_id, contest.name, json.dumps(list(contest.task_refs)), contest.status, json.dumps(contest.metadata, sort_keys=True)),
            )
        return contest

    def get_contest(self, contest_id: str) -> Contest | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM contests WHERE contest_id=?", (contest_id,)).fetchone()
        if row is None:
            return None
        return Contest(row["contest_id"], row["name"], tuple(json.loads(row["task_refs_json"])), row["status"], json.loads(row["metadata_json"]))

    def register_contestant(self, contest_id: str, user_id: str) -> None:
        with self._connect() as db:
            db.execute("INSERT INTO contest_registrations(contest_id,user_id,registered_at) VALUES(?,?,datetime('now')) ON CONFLICT DO NOTHING", (contest_id, user_id))

    def is_registered(self, contest_id: str, user_id: str) -> bool:
        with self._connect() as db:
            return db.execute("SELECT 1 FROM contest_registrations WHERE contest_id=? AND user_id=?", (contest_id, user_id)).fetchone() is not None

    def list_contests(self) -> list[Contest]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM contests ORDER BY contest_id").fetchall()
        return [self.get_contest(row["contest_id"]) for row in rows]  # type: ignore[misc]

    def save_submission(self, submission: Submission) -> Submission:
        with self._connect() as db:
            db.execute(
                """INSERT INTO submissions(submission_id,contestant_id,task_ref,artifact_path,contest_id,metadata_json)
                   VALUES(?,?,?,?,?,?) ON CONFLICT(submission_id) DO UPDATE SET metadata_json=excluded.metadata_json""",
                (submission.submission_id, submission.contestant_id, submission.task_ref, submission.artifact_path, submission.contest_id, json.dumps(submission.metadata, sort_keys=True)),
            )
        return submission

    def list_submissions(self, *, contestant_id: str | None = None, contest_id: str | None = None) -> list[Submission]:
        clauses: list[str] = []
        params: list[str] = []
        if contestant_id:
            clauses.append("contestant_id=?")
            params.append(contestant_id)
        if contest_id:
            clauses.append("contest_id=?")
            params.append(contest_id)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._connect() as db:
            rows = db.execute("SELECT * FROM submissions" + where + " ORDER BY submission_id DESC", params).fetchall()
        return [Submission(row["submission_id"], row["contestant_id"], row["task_ref"], row["artifact_path"], row["contest_id"], json.loads(row["metadata_json"])) for row in rows]

    def update_submission_result(self, submission_id: str, result: dict[str, Any]) -> None:
        submission = self.get_submission(submission_id)
        if submission is None:
            raise KeyError(f"unknown submission: {submission_id}")
        metadata = {**submission.metadata, "result": result}
        self.save_submission(Submission(submission.submission_id, submission.contestant_id, submission.task_ref, submission.artifact_path, submission.contest_id, metadata))

    def get_submission(self, submission_id: str) -> Submission | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM submissions WHERE submission_id=?", (submission_id,)).fetchone()
        if row is None:
            return None
        return Submission(row["submission_id"], row["contestant_id"], row["task_ref"], row["artifact_path"], row["contest_id"], json.loads(row["metadata_json"]))

    def record_leaderboard(self, entry: LeaderboardEntry) -> LeaderboardEntry:
        with self._connect() as db:
            db.execute(
                """INSERT INTO leaderboard(evaluation_id,contestant_id,contest_id,task_ref,score,visible,metadata_json)
                   VALUES(?,?,?,?,?,?,?) ON CONFLICT(evaluation_id) DO UPDATE SET score=excluded.score,
                   visible=excluded.visible,metadata_json=excluded.metadata_json""",
                (entry.evaluation_id, entry.contestant_id, entry.contest_id, entry.task_ref, entry.score, int(entry.visible), json.dumps(entry.metadata, sort_keys=True)),
            )
            db.execute(
                "INSERT INTO leaderboard_history(revision_id,evaluation_id,contest_id,contestant_id,task_ref,score,recorded_at,payload_json) VALUES(?,?,?,?,?,?,datetime('now'),?)",
                (secrets.token_hex(16), entry.evaluation_id, entry.contest_id, entry.contestant_id, entry.task_ref, entry.score, json.dumps(entry.as_dict(), sort_keys=True)),
            )
        return entry

    def record(self, entry: LeaderboardEntry) -> None:
        self.record_leaderboard(entry)

    def accept_callback_event(self, event_id: str) -> bool:
        """Atomically accept an event ID once; retries return ``False``."""
        if not event_id.strip():
            raise ValueError("event_id is required")
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO callback_events(event_id,received_at) VALUES(?,datetime('now')) ON CONFLICT(event_id) DO NOTHING",
                (event_id.strip(),),
            )
        return cursor.rowcount == 1

    def list_leaderboard(self, contest_id: str, *, visible_only: bool = True) -> list[LeaderboardEntry]:
        contest = self.get_contest(contest_id)
        policy = contest.metadata if contest else {}
        query = "SELECT * FROM leaderboard WHERE contest_id=?"
        params: list[Any] = [contest_id]
        if visible_only:
            query += " AND visible=1"
        query += " ORDER BY score DESC NULLS LAST, contestant_id, task_ref"
        with self._connect() as db:
            rows = db.execute(query, params).fetchall()
        entries = [
            LeaderboardEntry(row["contestant_id"], row["contest_id"], row["task_ref"], row["score"], row["evaluation_id"], bool(row["visible"]), json.loads(row["metadata_json"]))
            for row in rows
        ]
        if policy.get("best_attempt", False):
            best: dict[tuple[str, str], LeaderboardEntry] = {}
            for entry in entries:
                key = (entry.contestant_id, entry.task_ref)
                if key not in best or (entry.score is not None and (best[key].score is None or entry.score > best[key].score)):
                    best[key] = entry
            entries = list(best.values())
        entries.sort(key=lambda entry: (entry.score is None, -(entry.score or 0), entry.contestant_id, entry.task_ref))
        ranked: list[LeaderboardEntry] = []
        last_score: float | None = None
        last_rank = 0
        for index, entry in enumerate(entries, start=1):
            if entry.score != last_score:
                last_rank = index
                last_score = entry.score
            ranked.append(LeaderboardEntry(entry.contestant_id, entry.contest_id, entry.task_ref, entry.score, entry.evaluation_id, entry.visible, {**entry.metadata, "rank": last_rank}))
        return ranked

    def leaderboard_history(self, contest_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM leaderboard_history WHERE contest_id=? ORDER BY recorded_at", (contest_id,)).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]
