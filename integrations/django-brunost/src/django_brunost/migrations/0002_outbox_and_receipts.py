import uuid

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [  # noqa: RUF012
        ("django_brunost", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [  # noqa: RUF012
        migrations.AddField(
            model_name="submission",
            name="artifact_path",
            field=models.CharField(default="", max_length=1000),
        ),
        migrations.AlterField(
            model_name="submission",
            name="artifact_id",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
        migrations.AddField(
            model_name="callbackreceipt",
            name="attempts",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="callbackreceipt",
            name="last_error",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="callbackreceipt",
            name="status",
            field=models.CharField(default="processing", max_length=20),
        ),
        migrations.AddField(
            model_name="callbackreceipt",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.CreateModel(
            name="SubmissionDispatchOutbox",
            fields=[
                ("outbox_id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("status", models.CharField(default="pending", max_length=20)),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("next_attempt_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("payload", models.JSONField(default=dict)),
                ("judge_evaluation_id", models.CharField(blank=True, default="", max_length=120)),
                ("last_error", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("submission", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="dispatch_outbox", to="django_brunost.submission")),
            ],
            options={"indexes": [models.Index(fields=("status", "next_attempt_at"), name="django_brun_status_6d3ac6_idx")]},
        ),
    ]
