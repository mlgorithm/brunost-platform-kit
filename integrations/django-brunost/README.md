# django-brunost

Installable Django integration for Brunost Platform Kit. It keeps Django
users, contest registration, submission history, and leaderboard projections in
the platform database while sending only immutable artifact IDs to Brunost
Judge.

```bash
pip install django-brunost
python manage.py migrate
python manage.py brunost_doctor
```

Add `django_brunost` to `INSTALLED_APPS`, include `django_brunost.urls`, and
configure `BRUNOST_JUDGE_URL`, `BRUNOST_JUDGE_API_TOKEN`, and
`BRUNOST_JUDGE_CALLBACK_SECRET`. Use `submit_submission(...)` to create a
durable local submission and outbox row, then run
`python manage.py brunost_dispatch_submissions` from a worker. The worker
uploads the directory and submits an idempotent evaluation outside the local
database transaction. The callback endpoint verifies the signed event ID and
optional `BRUNOST_PLATFORM_CALLBACK_TOKEN`, then commits the submission,
leaderboard projection, and receipt in one transaction. The leaderboard URL
uses the shared versioned policy (`best_attempt`, `sum`, `average`, `max`, and
standard/dense/ordinal ties).
