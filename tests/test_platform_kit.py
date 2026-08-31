import py_compile
from pathlib import Path

import pytest

from brunost_platform.application import PlatformApplication
from brunost_platform.callbacks import verify_judge_callback
from brunost_platform.models import Submission
from brunost_platform.project import TASK_KINDS, create_contest, create_project, create_task, template_files
from brunost_platform.store import SQLitePlatformStore


class FakeJudge:
    def __init__(self):
        self.calls = []

    def submit_evaluation(self, **kwargs):
        self.calls.append(kwargs)
        return {"evaluation_id": "eval-1", "execution_id": "eval-1", "status": "queued", "score": None}

    def upload_artifact(self, path):
        self.uploaded = path
        return {"artifact_id": "a" * 64}

    def cancel(self, evaluation_id):
        return {"evaluation_id": evaluation_id, "status": "canceled"}

    def get_evaluation(self, evaluation_id):
        return {"evaluation_id": evaluation_id}

    def health(self):
        return {"status": "ok"}


def test_templates_are_complete(tmp_path: Path):
    assert {"python-fastapi", "node-fastify", "minimal"} <= set(__import__("brunost_platform.project", fromlist=["TEMPLATES"]).TEMPLATES)
    for template in ("python-fastapi", "node-fastify", "minimal"):
        create_project(tmp_path / template, template=template)
        assert (tmp_path / template / "README.md").is_file()
    py_compile.compile(str(tmp_path / "python-fastapi" / "app" / "main.py"), doraise=True)
    assert (tmp_path / "python-fastapi" / "docker-compose.yml").is_file()
    assert "src/server.ts" in template_files("node-fastify", "demo")
    assert "brunost-platform-kit[postgres]>=0.3,<0.4" in template_files("python-fastapi", "demo")["pyproject.toml"]


def test_reference_template_has_headless_premium_identity_boundary():
    source = template_files("python-fastapi", "demo")["app/main.py"]
    assert "BRUNOST_PLATFORM_SERVICE_TOKEN" in source
    assert "x-brunost-subject" in source
    assert "x-brunost-roles" in source


def test_init_refuses_to_overwrite(tmp_path: Path):
    root = tmp_path / "existing"
    root.mkdir()
    (root / "keep.txt").write_text("keep")
    with pytest.raises(FileExistsError):
        create_project(root, template="minimal")


def test_application_submits_and_keeps_leaderboard_private(tmp_path: Path):
    judge = FakeJudge()
    app = PlatformApplication(judge, store=SQLitePlatformStore(tmp_path / "platform.db"))
    result = app.submit(Submission("submission-1", "student-1", "coding/v1", "/tmp/submission", "contest-1"), evaluation_kind="batch")
    assert result["evaluation_id"] == "eval-1"
    assert judge.calls[0]["evaluation_kind"] == "batch"
    assert judge.calls[0]["submission_artifact_id"] == "a" * 64
    assert judge.calls[0]["metadata"]["contest_id"] == "contest-1"


def test_uninstalled_agent_runner_fails_closed(tmp_path: Path):
    app = PlatformApplication(FakeJudge(), store=SQLitePlatformStore(tmp_path / "platform.db"))
    with pytest.raises(NotImplementedError, match="runner plugin"):
        app.submit(Submission("submission-1", "student-1", "coding/v1", "/tmp/submission", "contest-1"), evaluation_kind="agent")


def test_task_and_contest_scaffolding(tmp_path: Path):
    contest = create_contest(tmp_path / "contest", contest_id="national-2026")
    assert TASK_KINDS == ("coding", "model", "optimization", "quiz")
    for kind in TASK_KINDS:
        task = create_task(tmp_path / kind, kind=kind)
        manifest = (task / "judge.yaml").read_text(encoding="utf-8")
        assert f"kind: {kind}" in manifest
        assert (task / "public").is_dir()
        assert (task / "private").is_dir()
    assert "id: national-2026" in (contest / "contest.yaml").read_text()


def test_callback_signature_requires_event_id():
    import hashlib
    import hmac
    import time

    event_id = "execution:1:result"
    timestamp = str(int(time.time()))
    body = b'{"status":"completed"}'
    signature = "sha256=" + hmac.new(
        b"secret", f"{timestamp}.{event_id}.".encode() + body, hashlib.sha256
    ).hexdigest()
    headers = {
        "X-Brunost-Judge-Timestamp": timestamp,
        "X-Brunost-Judge-Event-ID": event_id,
        "X-Brunost-Judge-Signature": signature,
    }
    assert verify_judge_callback(body, headers, "secret") == event_id
    headers["X-Brunost-Judge-Event-ID"] = "execution:2:result"
    assert verify_judge_callback(body, headers, "secret") is None
