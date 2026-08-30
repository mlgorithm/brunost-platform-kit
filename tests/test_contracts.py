import pytest

from brunost_platform.contracts import (
    ArtifactSubmission,
    ContractValidationError,
    EvaluationRequest,
    ResultEnvelope,
    TaskRegistration,
    normalize_result,
)
from brunost_platform.gateway import HttpJudgeGateway


def test_task_registration_requires_one_artifact_reference_and_emits_judge_payload():
    artifact_id = "A" * 64
    task = TaskRegistration(
        task_ref="contest/quiz-1",
        kind="quiz",
        artifact_id=artifact_id,
        runtime="python-3.13",
        metadata={"title": "Quiz 1"},
    )

    assert task.to_payload() == {
        "task_ref": "contest/quiz-1",
        "kind": "quiz",
        "artifact_id": "a" * 64,
        "version": 1,
        "runtime": "python-3.13",
        "metadata": {"title": "Quiz 1"},
    }

    with pytest.raises(ContractValidationError, match="exactly one"):
        TaskRegistration(task_ref="contest/task", kind="code")
    with pytest.raises(ContractValidationError, match="exactly one"):
        TaskRegistration(task_ref="contest/task", kind="code", artifact_id=artifact_id, path="/tmp/task")


def test_artifact_submission_and_evaluation_request_share_immutable_artifact():
    submission = ArtifactSubmission(
        submission_id="submission-1",
        contestant_id="student-1",
        task_ref="contest/model",
        artifact_id="b" * 64,
        contest_id="contest-1",
        metadata={"language": "python"},
    )
    request = EvaluationRequest.from_submission(
        submission,
        evaluation_kind="batch",
        metadata={"source": "premium"},
    )

    assert request.to_payload() == {
        "task_ref": "contest/model",
        "submission_artifact_id": "b" * 64,
        "idempotency_key": "submission-1",
        "evaluation_kind": "batch",
        "agent_refs": [],
        "game_ref": None,
        "seed": None,
        "callback_url": None,
        "callback_token": None,
        "metadata": {"language": "python", "source": "premium"},
        "queue": "default",
        "resource_class": "cpu",
        "priority": 0,
    }
    with pytest.raises((AttributeError, TypeError)):
        submission.artifact_id = "c" * 64
    with pytest.raises(ContractValidationError, match="SHA-256"):
        EvaluationRequest(task_ref="contest/model", submission_artifact_id="not-an-artifact", idempotency_key="x")


def test_result_normalization_accepts_execution_id_only_and_keeps_extra_fields():
    result = normalize_result(
        {
            "execution_id": "exec-1",
            "status": "completed",
            "score": 0.875,
            "metrics": {"accuracy": 0.875},
            "artifacts": [{"artifact_id": "c" * 64, "name": "model file.bin", "size_bytes": 12}],
            "runtime_image": "python-3.13-ml-v1",
        }
    )

    assert isinstance(result, ResultEnvelope)
    assert result.evaluation_id == "exec-1"
    assert result.execution_id == "exec-1"
    assert result.artifacts[0].name == "model file.bin"
    assert result.metadata["runtime_image"] == "python-3.13-ml-v1"
    assert result.to_dict()["artifacts"][0]["artifact_id"] == "c" * 64

    with pytest.raises(ContractValidationError, match="evaluation_id"):
        ResultEnvelope.from_payload({"status": "failed"})
    with pytest.raises(ContractValidationError, match="finite"):
        ResultEnvelope.from_payload({"evaluation_id": "eval-1", "status": "completed", "score": float("nan")})


def test_gateway_typed_requests_and_legacy_keywords_use_same_wire_shape(monkeypatch):
    gateway = HttpJudgeGateway(base_url="https://judge.example.test")
    calls = []

    def fake_request(method, path, payload=None):
        calls.append((method, path, payload))
        return {"evaluation_id": "eval-1", "status": "queued"}

    monkeypatch.setattr(gateway, "_request", fake_request)
    task = TaskRegistration(task_ref="contest/task", kind="code", artifact_id="d" * 64)
    request = EvaluationRequest(task_ref="contest/task", submission_artifact_id="e" * 64, idempotency_key="submission-1")
    gateway.register_task(task)
    gateway.submit_evaluation(request)
    gateway.submit_evaluation(
        task_ref="contest/task",
        submission_artifact_id="e" * 64,
        idempotency_key="submission-1",
    )

    assert calls[0] == ("POST", "/v1/tasks", task.to_payload())
    assert calls[1] == ("POST", "/v1/evaluations", request.to_payload())
    assert calls[2] == calls[1]


def test_gateway_can_normalize_a_polled_result(monkeypatch):
    gateway = HttpJudgeGateway(base_url="https://judge.example.test")
    monkeypatch.setattr(
        gateway,
        "_request",
        lambda method, path, payload=None: {"evaluation_id": "eval-2", "status": "failed", "failure_reason": "timeout"},
    )

    result = gateway.get_evaluation_result("eval-2")

    assert result.evaluation_id == "eval-2"
    assert result.status == "failed"
    assert result.failure_reason == "timeout"
