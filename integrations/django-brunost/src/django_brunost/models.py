from django.conf import settings
from django.db import models


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
    artifact_id = models.CharField(max_length=128)
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
    event_id = models.CharField(max_length=255, unique=True)
    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="callback_receipts")
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
