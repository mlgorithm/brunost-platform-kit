import os
import uuid

from django.db import transaction

from brunost_platform.application import PlatformApplication
from brunost_platform.gateway import gateway_from_environment

from .models import Contest, Submission


def platform_application() -> PlatformApplication:
    """Return the configured framework-neutral application service.

    Django models remain the source of truth for a Django deployment; this
    helper is intended for artifact transport and callback verification at the
    HTTP boundary.
    """
    return PlatformApplication(gateway_from_environment())


@transaction.atomic
def submit_submission(*, contestant, contest: Contest, task_ref: str, artifact_path: str, submission_id: str | None = None, callback_url: str | None = None, callback_token: str | None = None) -> dict:
    """Upload a Django submission and create its Judge evaluation.

    The local path is consumed only by the Django process. The Judge receives
    the resulting immutable artifact ID, so this works when the Judge runs on
    another country node or in a separate cluster.
    """
    if task_ref not in contest.task_refs:
        raise ValueError("task_ref is not part of the contest")
    submission_id = submission_id or str(uuid.uuid4())
    gateway = gateway_from_environment()
    artifact = gateway.upload_artifact(artifact_path)
    submission = Submission.objects.create(
        submission_id=submission_id,
        contestant=contestant,
        contest=contest,
        task_ref=task_ref,
        artifact_id=str(artifact["artifact_id"]),
    )
    result = gateway.submit_evaluation(
        task_ref=task_ref,
        submission_artifact_id=submission.artifact_id,
        idempotency_key=submission.submission_id,
        callback_url=callback_url or os.environ.get("BRUNOST_PLATFORM_CALLBACK_URL"),
        callback_token=callback_token or os.environ.get("BRUNOST_PLATFORM_CALLBACK_TOKEN"),
        metadata={"platform_submission_id": submission.submission_id, "contest_id": contest.contest_id, "contestant_id": str(contestant.pk)},
    )
    submission.evaluation_id = str(result.get("evaluation_id") or result.get("execution_id") or "")
    submission.save(update_fields=["evaluation_id", "updated_at"])
    return result


def callback_secret() -> str:
    return os.environ.get("BRUNOST_JUDGE_CALLBACK_SECRET", "")
