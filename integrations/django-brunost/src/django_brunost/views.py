import hmac
import json
import os

from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from brunost_platform.callbacks import verify_judge_callback

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
        submission = Submission.objects.get(pk=submission_id)
    except Submission.DoesNotExist:
        return JsonResponse({"detail": "unknown submission"}, status=404)
    _receipt, created = CallbackReceipt.objects.get_or_create(event_id=event_id, defaults={"submission": submission, "payload": payload})
    if not created:
        return JsonResponse({"status": "duplicate", "event_id": event_id})
    submission.status = payload.get("status", "failed")
    submission.score = payload.get("score")
    submission.metrics = payload.get("metrics") or {}
    submission.evaluation_id = payload.get("evaluation_id") or payload.get("execution_id", "")
    submission.save(update_fields=["status", "score", "metrics", "evaluation_id", "updated_at"])
    LeaderboardProjection.objects.update_or_create(
        evaluation_id=submission.evaluation_id,
        defaults={"contest": submission.contest, "contestant": submission.contestant, "task_ref": submission.task_ref, "score": submission.score, "visible": bool(submission.contest.policy.get("leaderboard_visible", False)), "metadata": {"status": submission.status, "metrics": submission.metrics}},
    )
    return JsonResponse({"status": submission.status, "event_id": event_id})


def leaderboard(request: HttpRequest, contest_id: str) -> JsonResponse:
    """Return the platform-owned best-attempt leaderboard for a contest."""
    contest = Contest.objects.get(contest_id=contest_id)
    if not contest.policy.get("leaderboard_visible", False):
        return JsonResponse([], safe=False)
    rows = LeaderboardProjection.objects.filter(contest=contest, visible=True).order_by("-score", "contestant_id", "task_ref")
    best: dict[tuple[int, str], LeaderboardProjection] = {}
    for row in rows:
        key = (row.contestant_id, row.task_ref)
        if contest.policy.get("best_attempt", True) and key in best:
            continue
        best[key] = row
    output = []
    for rank, row in enumerate(best.values(), start=1):
        output.append({"rank": rank, "contestant_id": row.contestant_id, "task_ref": row.task_ref, "score": row.score, "metadata": row.metadata})
    return JsonResponse(output, safe=False)
