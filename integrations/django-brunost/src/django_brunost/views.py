import hmac
import json
import os
from datetime import timedelta

from django.db import transaction
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from brunost_platform.callbacks import verify_judge_callback
from brunost_platform.leaderboard_policy import normalize_policy, project_leaderboard
from brunost_platform.models import LeaderboardEntry

from .models import CallbackReceipt, Contest, LeaderboardProjection, Submission
from .services import callback_secret


@csrf_exempt
def judge_callback(request: HttpRequest) -> JsonResponse:
    if request.method != "POST":
        return JsonResponse({"detail": "POST required"}, status=405)
    expected_token = os.environ.get("BRUNOST_PLATFORM_CALLBACK_TOKEN", "")
    if expected_token and not hmac.compare_digest(request.headers.get("Authorization", ""), f"Bearer {expected_token}"):
        return JsonResponse({"detail": "invalid callback bearer token"}, status=401)
    event_id = verify_judge_callback(request.body, request.headers, callback_secret())
    if not event_id:
        return JsonResponse({"detail": "invalid callback signature"}, status=401)
    payload = json.loads(request.body.decode("utf-8"))
    submission_id = str((payload.get("metadata") or {}).get("platform_submission_id", ""))
    try:
        with transaction.atomic():
            submission = Submission.objects.select_for_update().select_related("contest").get(pk=submission_id)
            receipt = CallbackReceipt.objects.select_for_update().filter(event_id=event_id).first()
            if receipt is not None:
                if receipt.submission_id != submission.submission_id or receipt.status == CallbackReceipt.STATUS_APPLIED:
                    return JsonResponse({"status": "duplicate", "event_id": event_id})
                if receipt.status == CallbackReceipt.STATUS_PROCESSING and receipt.updated_at >= timezone.now() - timedelta(minutes=15):
                    return JsonResponse({"status": "duplicate", "event_id": event_id})
                receipt.status = CallbackReceipt.STATUS_PROCESSING
                receipt.attempts += 1
                receipt.payload = payload
                receipt.last_error = ""
                receipt.save(update_fields=["status", "attempts", "payload", "last_error", "updated_at"])
            else:
                receipt = CallbackReceipt.objects.create(
                    event_id=event_id,
                    submission=submission,
                    payload=payload,
                    status=CallbackReceipt.STATUS_PROCESSING,
                )
            submission.status = payload.get("status", "failed")
            submission.score = payload.get("score")
            submission.metrics = payload.get("metrics") or {}
            submission.evaluation_id = payload.get("evaluation_id") or payload.get("execution_id", "")
            submission.save(update_fields=["status", "score", "metrics", "evaluation_id", "updated_at"])
            LeaderboardProjection.objects.update_or_create(
                evaluation_id=submission.evaluation_id,
                defaults={"contest": submission.contest, "contestant": submission.contestant, "task_ref": submission.task_ref, "score": submission.score, "visible": normalize_policy(submission.contest.policy).visible, "metadata": {"status": submission.status, "metrics": submission.metrics, "event_id": event_id, "recorded_at": timezone.now().isoformat()}},
            )
            receipt.status = CallbackReceipt.STATUS_APPLIED
            receipt.last_error = ""
            receipt.save(update_fields=["status", "last_error", "updated_at"])
    except Submission.DoesNotExist:
        return JsonResponse({"detail": "unknown submission"}, status=404)
    except Exception as exc:  # noqa: BLE001
        CallbackReceipt.objects.filter(event_id=event_id).update(status=CallbackReceipt.STATUS_FAILED, last_error=str(exc)[:4000], updated_at=timezone.now())
        return JsonResponse({"detail": "callback projection failed", "event_id": event_id}, status=500)
    return JsonResponse({"status": submission.status, "event_id": event_id})


def leaderboard(request: HttpRequest, contest_id: str) -> JsonResponse:
    """Return the platform-owned best-attempt leaderboard for a contest."""
    contest = Contest.objects.get(contest_id=contest_id)
    policy = normalize_policy(contest.policy)
    if not policy.visible:
        return JsonResponse([], safe=False)
    rows = LeaderboardProjection.objects.filter(contest=contest, visible=True).order_by("contestant_id", "task_ref")
    entries = [
        LeaderboardEntry(
            contestant_id=str(row.contestant_id),
            contest_id=contest.contest_id,
            task_ref=row.task_ref,
            score=row.score,
            evaluation_id=row.evaluation_id,
            visible=row.visible,
            metadata={**row.metadata, "recorded_at": row.revised_at.isoformat()},
        )
        for row in rows
    ]
    projected = project_leaderboard(entries, contest.policy)
    return JsonResponse([entry.as_dict() for entry in projected], safe=False)
