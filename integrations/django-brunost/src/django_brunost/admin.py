from django.contrib import admin

from .models import CallbackReceipt, Contest, LeaderboardProjection, Submission, SubmissionDispatchOutbox

admin.site.register((Contest, Submission, LeaderboardProjection, CallbackReceipt, SubmissionDispatchOutbox))
