import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [(migrations.swappable_dependency(settings.AUTH_USER_MODEL))]  # noqa: RUF012
    operations = [  # noqa: RUF012
        migrations.CreateModel(
            name="Contest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("contest_id", models.CharField(max_length=120, unique=True)),
                ("name", models.CharField(max_length=200)),
                ("task_refs", models.JSONField(default=list)),
                ("status", models.CharField(default="draft", max_length=32)),
                ("policy", models.JSONField(default=dict)),
            ],
            options={"ordering": ("contest_id",)},
        ),
        migrations.CreateModel(
            name="Submission",
            fields=[
                ("submission_id", models.CharField(max_length=120, primary_key=True, serialize=False)),
                ("task_ref", models.CharField(max_length=200)),
                ("artifact_id", models.CharField(max_length=128)),
                ("evaluation_id", models.CharField(blank=True, max_length=120)),
                ("status", models.CharField(default="queued", max_length=32)),
                ("score", models.FloatField(blank=True, null=True)),
                ("metrics", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("contest", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="submissions", to="django_brunost.contest")),
                ("contestant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="LeaderboardProjection",
            fields=[
                ("evaluation_id", models.CharField(max_length=120, primary_key=True, serialize=False)),
                ("task_ref", models.CharField(max_length=200)),
                ("score", models.FloatField(blank=True, null=True)),
                ("visible", models.BooleanField(default=False)),
                ("metadata", models.JSONField(default=dict)),
                ("revised_at", models.DateTimeField(auto_now=True)),
                ("contest", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="leaderboard", to="django_brunost.contest")),
                ("contestant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="CallbackReceipt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_id", models.CharField(max_length=255, unique=True)),
                ("payload", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("submission", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="callback_receipts", to="django_brunost.submission")),
            ],
        ),
    ]
