import hashlib
import hmac
import json
import time
from pathlib import Path

from brunost_platform.application import PlatformApplication
from brunost_platform.identity import LocalIdentityAdapter
from brunost_platform.leaderboard_policy import project_leaderboard
from brunost_platform.models import Contest, LeaderboardEntry, Submission, User, WorkerOperation
from brunost_platform.store import SQLitePlatformStore


class FakeJudge:
    def health(self):
        return {"status": "ok"}

    def submit_evaluation(self, **kwargs):
        return {"evaluation_id": kwargs["idempotency_key"], "execution_id": kwargs["idempotency_key"], "status": "queued", "score": None}

    def upload_artifact(self, path):
        return {"artifact_id": "b" * 64}

    def cancel(self, evaluation_id):
        return {"evaluation_id": evaluation_id, "status": "canceled"}

    def get_evaluation(self, evaluation_id):
        return {"evaluation_id": evaluation_id}


def test_sqlite_store_and_result_projection(tmp_path: Path):
    store = SQLitePlatformStore(tmp_path / "platform.db")
    store.save_user(User("u1", "u@example.test", "Student", roles=("contestant",)))
    store.create_contest(Contest("c1", "National Final", ("coding/v1",)))
    app = PlatformApplication(FakeJudge(), store=store)
    submission = Submission("s1", "u1", "coding/v1", "/tmp/submission", "c1")
    queued = app.submit(submission, evaluation_kind="batch")
    assert queued["status"] == "queued"
    app.record_result(submission, {"evaluation_id": "s1", "status": "completed", "score": 0.9}, visible=True)
    assert store.list_leaderboard("c1")[0].score == 0.9
    assert store.get_user("u1").display_name == "Student"  # type: ignore[union-attr]


def test_identity_session_and_callback_project_automatically(tmp_path: Path):
    store = SQLitePlatformStore(tmp_path / "platform.db")
    identity = LocalIdentityAdapter(store)
    user = identity.register(email="u@example.test", password="long-enough-password", display_name="Student")
    assert identity.authenticate(email=user.email, password="long-enough-password")
    contest = store.create_contest(Contest("c1", "Final", ("coding/v1",), metadata={"leaderboard_visible": True, "best_attempt": True}))
    submission = Submission("s1", user.user_id, "coding/v1", str(tmp_path), contest.contest_id)
    store.register_contestant(contest.contest_id, user.user_id)
    app = PlatformApplication(FakeJudge(), store=store)
    app.submit(submission)
    event_id = "execution:s1:result"
    body = json.dumps({"evaluation_id": "s1", "status": "completed", "score": 0.9, "metrics": {}, "metadata": {"platform_submission_id": "s1"}}, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    signature = "sha256=" + hmac.new(b"secret", f"{timestamp}.{event_id}.".encode() + body, hashlib.sha256).hexdigest()
    headers = {"X-Brunost-Judge-Timestamp": timestamp, "X-Brunost-Judge-Event-ID": event_id, "X-Brunost-Judge-Signature": signature}
    assert app.handle_callback(body, headers, secret="secret")["status"] == "completed"
    assert app.handle_callback(body, headers, secret="secret")["status"] == "duplicate"
    assert store.list_leaderboard("c1")[0].score == 0.9


def test_versioned_leaderboard_policy_aggregates_and_recovers_failed_callback(tmp_path: Path):
    entries = [
        LeaderboardEntry("a", "c1", "t1", 4, "a-1", True),
        LeaderboardEntry("a", "c1", "t2", 6, "a-2", True),
        LeaderboardEntry("b", "c1", "t1", 10, "b-1", True),
    ]
    projected = project_leaderboard(entries, {"leaderboard_policy": {"aggregation": "sum", "tie_policy": "dense", "visible": True}})
    assert [(row.contestant_id, row.score, row.metadata["rank"]) for row in projected] == [("a", 10, 1), ("b", 10, 1)]

    store = SQLitePlatformStore(tmp_path / "recovery.db")
    store.save_user(User("u1", "u@example.test", "Student"))
    store.create_contest(Contest("c1", "Final", ("t1",), metadata={"leaderboard_visible": True}))
    submission = Submission("s1", "u1", "t1", str(tmp_path), "c1")
    store.save_submission(submission)
    body = {"status": "completed", "score": 1.0, "metadata": {"platform_submission_id": "s1"}}
    assert store.claim_callback_event("event-1", submission_id="s1", payload=body) == "claimed"
    store.mark_callback_failed("event-1", RuntimeError("projection interrupted"))
    assert store.claim_callback_event("event-1", submission_id="s1", payload=body) == "claimed"


def test_worker_operations_are_durable_and_filterable(tmp_path: Path):
    store = SQLitePlatformStore(tmp_path / "workers.db")
    operation = WorkerOperation(
        operation_id="op-1",
        worker_id="worker-1",
        action="pause",
        status="succeeded",
        actor_user_id="admin-1",
        actor_email="admin@example.test",
        reason="Maintenance window",
        requested_at="2026-08-29T10:00:00+00:00",
        completed_at="2026-08-29T10:00:01+00:00",
        response={"worker_id": "worker-1", "draining": True},
    )
    store.record_worker_operation(operation)
    assert store.list_worker_operations(limit=1)[0] == operation
    assert store.list_worker_operations(worker_id="other") == []
