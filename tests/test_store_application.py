import hashlib
import hmac
import json
import time
from pathlib import Path

from brunost_platform.application import PlatformApplication
from brunost_platform.identity import LocalIdentityAdapter
from brunost_platform.models import Contest, Submission, User
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
    store.create_contest(Contest("c1", "National Final", ("ioai/v1",)))
    app = PlatformApplication(FakeJudge(), store=store)
    submission = Submission("s1", "u1", "ioai/v1", "/tmp/submission", "c1")
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
    contest = store.create_contest(Contest("c1", "Final", ("ioai/v1",), metadata={"leaderboard_visible": True, "best_attempt": True}))
    submission = Submission("s1", user.user_id, "ioai/v1", str(tmp_path), contest.contest_id)
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
