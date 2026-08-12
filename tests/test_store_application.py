from pathlib import Path

from brunost_platform.application import PlatformApplication
from brunost_platform.models import Contest, Submission, User
from brunost_platform.store import SQLitePlatformStore


class FakeJudge:
    def health(self):
        return {"status": "ok"}

    def submit_evaluation(self, **kwargs):
        return {"evaluation_id": kwargs["idempotency_key"], "execution_id": kwargs["idempotency_key"], "status": "queued", "score": None}

    def get_evaluation(self, evaluation_id):
        return {"evaluation_id": evaluation_id}


def test_sqlite_store_and_result_projection(tmp_path: Path):
    store = SQLitePlatformStore(tmp_path / "platform.db")
    store.save_user(User("u1", "u@example.test", "Student", roles=("contestant",)))
    store.create_contest(Contest("c1", "National Final", ("ioai/v1",)))
    app = PlatformApplication(FakeJudge(), store=store)
    submission = Submission("s1", "u1", "ioai/v1", "/tmp/submission", "c1")
    queued = app.submit(submission, evaluation_kind="agent")
    assert queued["status"] == "queued"
    app.record_result(submission, {"evaluation_id": "s1", "status": "completed", "score": 0.9}, visible=True)
    assert store.list_leaderboard("c1")[0].score == 0.9
    assert store.get_user("u1").display_name == "Student"  # type: ignore[union-attr]
