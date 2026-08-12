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
`BRUNOST_JUDGE_CALLBACK_SECRET`. Use `submit_submission(...)` to upload a
directory and create an evaluation; the callback endpoint verifies the signed
event ID and optional `BRUNOST_PLATFORM_CALLBACK_TOKEN` before applying a
result once. The leaderboard URL applies contest visibility and best-attempt
policy.
