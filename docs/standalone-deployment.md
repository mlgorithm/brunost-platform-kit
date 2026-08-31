# Standalone platform deployment

This guide deploys the open-source Platform Kit as a contest website without
Premium. The platform owns accounts, contests, submissions, and leaderboard
policy. Brunost Judge owns task packages, artifacts, scheduling, execution,
and signed result delivery.

## Prerequisites

1. Deploy Judge and at least one enrolled worker using `brunost-deploy`.
2. Create a scoped Judge service token for the platform.
3. Choose SQLite for one application instance or PostgreSQL for multiple
   instances. SQLite is not suitable for an active multi-replica website.
4. Expose the platform callback URL over HTTPS and add its hostname to the
   Judge callback allowlist.

## Create the application

```bash
python -m pip install 'brunost-platform-kit[postgres]>=0.3,<0.4'
brunost-platform init national-platform --template python-fastapi
cd national-platform
cp .env.example .env
```

Set the values in `.env` or your secret manager:

```bash
BRUNOST_JUDGE_URL=https://judge.example.org
BRUNOST_JUDGE_API_TOKEN=<scoped-service-token>
BRUNOST_PLATFORM_CALLBACK_URL=https://platform.example.org/api/judge/callback
BRUNOST_PLATFORM_CALLBACK_TOKEN=<random-bearer-token>
BRUNOST_JUDGE_CALLBACK_SECRET=<random-shared-signing-secret>
BRUNOST_PLATFORM_DATABASE=postgresql://platform:<password>@db.example/platform
BRUNOST_DEFAULT_ADMIN_EMAIL=admin@example.org
BRUNOST_DEFAULT_ADMIN_PASSWORD=<unique-temporary-password>
```

The callback signing secret must equal Judge's
`BRUNOST_JUDGE_CALLBACK_SIGNING_SECRET`. Keep both secrets outside source
control. Change the bootstrap password at first login.

## Publish a task and contest

The UI can create a valid starter package, but an official task must be
reviewed and tested before publishing. The production flow is:

1. Scaffold a family-specific package with `brunost-platform task new`.
2. Complete the public statement/data, private assets, and evaluator.
3. Validate and upload the package with Judge, producing an immutable
   `artifact_id`.
4. Register a stable `task_ref` that points at that artifact.
5. Add the registered task reference to a Platform contest.

Platform submissions are uploaded as content-addressed artifacts. The platform
then creates an idempotent evaluation request and accepts only signed callback
updates. Browser-only Lab runtimes are not Judge tasks and must not be routed
through this deployment.

## Production checks

```bash
brunost-platform doctor
uv run pytest -q
uv run ruff check src tests
```

Before opening registration, verify Judge `/readyz`, worker availability, a
signed callback round trip, a task evaluation, and a backup/restore rehearsal.
Use the deployment repository's release-readiness checklist for the Judge
cluster itself.
