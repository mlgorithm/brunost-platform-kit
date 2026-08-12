import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class Contest(models.Model):
    contest_id = models.CharField(max_length=120, unique=True)
    name = models.CharField(max_length=200)
    task_refs = models.JSONField(default=list)
    status = models.CharField(max_length=32, default="draft")
    policy = models.JSONField(default=dict)

    class Meta:
        ordering = ("contest_id",)


class Submission(models.Model):
    submission_id = models.CharField(max_length=120, primary_key=True)
    contestant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    contest = models.ForeignKey(Contest, on_delete=models.CASCADE, related_name="submissions")
    task_ref = models.CharField(max_length=200)
    # Filled by the dispatch worker after the local path has been uploaded to
    # Judge.  Keeping the path private to the platform avoids sending a
    # filesystem path across the service boundary.
    artifact_id = models.CharField(max_length=128, blank=True, default="")
    artifact_path = models.CharField(max_length=1000, blank=True, default="")
    evaluation_id = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=32, default="queued")
    score = models.FloatField(null=True, blank=True)
    metrics = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class LeaderboardProjection(models.Model):
    evaluation_id = models.CharField(max_length=120, primary_key=True)
    contest = models.ForeignKey(Contest, on_delete=models.CASCADE, related_name="leaderboard")
    contestant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    task_ref = models.CharField(max_length=200)
    score = models.FloatField(null=True, blank=True)
    visible = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict)
    revised_at = models.DateTimeField(auto_now=True)


class CallbackReceipt(models.Model):
    STATUS_PROCESSING = "processing"
    STATUS_APPLIED = "applied"
    STATUS_FAILED = "failed"

    event_id = models.CharField(max_length=255, unique=True)
    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="callback_receipts")
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=20, default=STATUS_PROCESSING)
    attempts = models.PositiveIntegerField(default=1)
    last_error = models.TextField(blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)


class SubmissionDispatchOutbox(models.Model):
    STATUS_PENDING = "pending"
    STATUS_SENDING = "sending"
    STATUS_SUBMITTED = "submitted"
    STATUS_FAILED = "failed"

    outbox_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    submission = models.OneToOneField(Submission, on_delete=models.CASCADE, related_name="dispatch_outbox")
    status = models.CharField(max_length=20, default=STATUS_PENDING)
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    payload = models.JSONField(default=dict)
    judge_evaluation_id = models.CharField(max_length=120, blank=True, default="")
    last_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=("status", "next_attempt_at"))]  # noqa: RUF012
