# Typed Judge contracts

`brunost_platform.contracts` is the shared, dependency-free contract layer
between Premium (or another platform) and Brunost Judge. It targets the
Judge 1.3.x HTTP shapes and is additive: applications may continue using the
existing `HttpJudgeGateway` keyword methods.

## Register a task

Use an immutable artifact ID in production. A local path is supported only for
development and remains mutually exclusive with an artifact ID:

```python
from brunost_platform import HttpJudgeGateway, TaskRegistration

judge = HttpJudgeGateway("https://judge.example/v1", token="service-token")
task = TaskRegistration(
    task_ref="national-final/quiz-1",
    kind="quiz",
    artifact_id="a" * 64,
    runtime="python-3.13",
    metadata={"title": "Quiz 1"},
)
judge.register_task(task)
```

`TaskRegistration` validates identifiers, the artifact/path one-of rule, and
JSON-compatible metadata before making a request. Its `to_payload()` result
matches the Judge 1.3.x registration payload.

## Submit an artifact

The platform should upload a submission directory first, then retain only the
content-addressed artifact ID at the service boundary:

```python
from brunost_platform import ArtifactSubmission, EvaluationRequest

submission = ArtifactSubmission(
    submission_id="submission-42",
    contestant_id="student-7",
    task_ref="national-final/model-1",
    artifact_id="b" * 64,
    contest_id="national-final",
)
request = EvaluationRequest.from_submission(
    submission,
    evaluation_kind="batch",
    callback_url="https://premium.example/api/judge/callback",
)
judge.submit_evaluation(request)
```

The frozen submission cannot be changed after construction, and the artifact
reference must be a SHA-256 digest. `EvaluationRequest` carries the same
artifact ID into the Judge request and validates queue, resource, callback,
and idempotency fields. The existing keyword form remains supported:

```python
judge.submit_evaluation(
    task_ref="national-final/model-1",
    submission_artifact_id="b" * 64,
    idempotency_key="submission-42",
)
```

## Normalize results

Polling responses and signed callback bodies can be normalized to one typed
envelope. The parser accepts the Judge's `evaluation_id` or its historical
`execution_id`-only response and retains additive response fields in
`metadata`:

```python
from brunost_platform import normalize_result

result = normalize_result(judge.get_evaluation("eval-42"))
if result.status == "completed":
    print(result.score, result.metrics)
```

`ResultEnvelope` contains the evaluation and execution IDs, status, score,
metrics, returned content-addressed artifacts, failure reason, and metadata.
Use `judge.get_evaluation_result("eval-42")` when the gateway should perform
the polling and normalization together. Raw `get_evaluation()` responses are
still available for existing integrations.

The contracts reject malformed IDs, non-finite scores, invalid artifact
records, oversized/non-JSON metadata, and missing required result fields with
`ContractValidationError` before the platform stores or forwards them.
