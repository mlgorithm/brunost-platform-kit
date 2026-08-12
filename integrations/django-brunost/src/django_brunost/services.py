import os
import uuid
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from brunost_platform.application import PlatformApplication
from brunost_platform.gateway import gateway_from_environment

from .models import Contest, Submission, SubmissionDispatchOutbox


def platform_application() -> PlatformApplication:
    """Return the configured framework-neutral application service.

    Django models remain the source of truth for a Django deployment; this
    helper is intended for artifact transport and callback verification at the
    HTTP boundary.
    """
    return PlatformApplication(gateway_from_environment())


def submit_submission(*, contestant, contest: Contest, task_ref: str, artifact_path: str, submission_id: str | None = None, callback_url: str | None = None, callback_token: str | None = None) -> dict:
    """Create a durable submission intent without doing network I/O.

    A worker should call :func:`dispatch_submission_outbox` after the commit.
    This prevents a Judge timeout from rolling back the platform submission or
    leaving an evaluation that has no local record.
    """
    if task_ref not in contest.task_refs:
        raise ValueError("task_ref is not part of the contest")
    submission_id = submission_id or str(uuid.uuid4())
    with transaction.atomic():
        submission = Submission.objects.create(
            submission_id=submission_id,
            contestant=contestant,
            contest=contest,
            task_ref=task_ref,
            artifact_path=artifact_path,
        )
        outbox = SubmissionDispatchOutbox.objects.create(
            submission=submission,
            payload={
                "callback_url": callback_url or os.environ.get("BRUNOST_PLATFORM_CALLBACK_URL"),
                "callback_token": callback_token or os.environ.get("BRUNOST_PLATFORM_CALLBACK_TOKEN"),
            },
        )
    return {"submission_id": submission.submission_id, "outbox_id": str(outbox.outbox_id), "status": "queued"}


def dispatch_submission_outbox(outbox_id: str | None = None) -> dict:
    """Upload and submit one outbox row, with retries safe by idempotency key."""
    now = timezone.now()
    with transaction.atomic():
        query = SubmissionDispatchOutbox.objects.select_for_update().select_related("submission", "submission__contest")
        if outbox_id:
            outbox = query.get(outbox_id=outbox_id)
            if outbox.status == SubmissionDispatchOutbox.STATUS_SUBMITTED:
                return {"status": "submitted", "submission_id": outbox.submission_id, "evaluation_id": outbox.judge_evaluation_id}
            if outbox.status == SubmissionDispatchOutbox.STATUS_SENDING and outbox.updated_at >= now - timedelta(minutes=15):
                return {"status": "sending", "submission_id": outbox.submission_id}
        else:
            outbox = query.filter(
                Q(status__in=[SubmissionDispatchOutbox.STATUS_PENDING, SubmissionDispatchOutbox.STATUS_FAILED], next_attempt_at__lte=now)
                | Q(status=SubmissionDispatchOutbox.STATUS_SENDING, updated_at__lt=now - timedelta(minutes=15))
            ).order_by("created_at").first()
        if outbox is None:
            return {"status": "empty"}
        outbox.status = SubmissionDispatchOutbox.STATUS_SENDING
        outbox.attempts += 1
        outbox.save(update_fields=["status", "attempts", "updated_at"])
        submission = outbox.submission
        contest = submission.contest
        payload = dict(outbox.payload or {})

    try:
        gateway = gateway_from_environment()
        artifact = gateway.upload_artifact(submission.artifact_path)
        artifact_id = str(artifact["artifact_id"])
        result = gateway.submit_evaluation(
            task_ref=submission.task_ref,
            submission_artifact_id=artifact_id,
            idempotency_key=submission.submission_id,
            callback_url=payload.get("callback_url"),
            callback_token=payload.get("callback_token"),
            metadata={
                "platform_submission_id": submission.submission_id,
                "contest_id": contest.contest_id,
                "contestant_id": str(submission.contestant_id),
            },
        )
    except Exception as exc:
        with transaction.atomic():
            current = SubmissionDispatchOutbox.objects.select_for_update().get(pk=outbox.outbox_id)
            delay = min(3600, 2 ** min(current.attempts, 10))
            current.status = SubmissionDispatchOutbox.STATUS_FAILED
            current.last_error = str(exc)[:4000]
            current.next_attempt_at = timezone.now() + timedelta(seconds=delay)
            current.save(update_fields=["status", "last_error", "next_attempt_at", "updated_at"])
        raise

    evaluation_id = str(result.get("evaluation_id") or result.get("execution_id") or "")
    with transaction.atomic():
        current = SubmissionDispatchOutbox.objects.select_for_update().get(pk=outbox.outbox_id)
        current.status = SubmissionDispatchOutbox.STATUS_SUBMITTED
        current.judge_evaluation_id = evaluation_id
        current.last_error = ""
        current.save(update_fields=["status", "judge_evaluation_id", "last_error", "updated_at"])
        Submission.objects.filter(pk=submission.submission_id).update(
            artifact_id=artifact_id,
            evaluation_id=evaluation_id,
            status="submitted",
            updated_at=timezone.now(),
        )
    return {**result, "submission_id": submission.submission_id, "artifact_id": artifact_id, "status": "submitted"}


def dispatch_pending_submissions(*, limit: int = 100) -> list[dict]:
    """Drain ready rows; a queue worker can call this periodically."""
    results: list[dict] = []
    for _ in range(max(0, limit)):
        result = dispatch_submission_outbox()
        if result.get("status") == "empty":
            break
        results.append(result)
    return results


def callback_secret() -> str:
    return os.environ.get("BRUNOST_JUDGE_CALLBACK_SECRET", "")
