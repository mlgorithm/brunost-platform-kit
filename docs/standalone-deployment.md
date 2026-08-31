# Standalone platform deployment

This guide deploys the open-source Platform Kit as a contest website without
Premium. The platform owns accounts, contests, submissions, and leaderboard
policy. Brunost Judge owns task packages, artifacts, scheduling, execution,
and signed result delivery.

## Prerequisites

1. Deploy Judge and at least one enrolled worker using `brunost-deploy`. Judge
   control-plane and workers can be on separate servers; Platform Kit never
   needs worker Docker access or Judge database access.
2. Declare the Platform hostname in the Judge callback allowlist and generate
   the connection template:

   ```bash
   brunostctl init judge-country --preset small --name judge-country \
     --public-url https://judge.example.org \
     --platform-url https://platform.example.org
   brunostctl platform-env --config judge-country/brunost.yaml \
     --platform-url https://platform.example.org \
     --output judge-country/platform.env.example
   ```

   For an existing topology, first add `platform.example.org` to
   `judge.callback_hosts`, render/redeploy the Judge configuration, then run
   `platform-env`. The generated file contains no secrets; use it as the Judge
   connection portion of the Platform application's `.env` or secret-manager
   configuration.
3. Inject a Platform service token and the callback-signing secret through your
   secret manager. The callback secret is the same value as the Judge
   `BRUNOST_JUDGE_CALLBACK_SIGNING_SECRET`; never copy the entire Judge `.env`
   file into Platform Kit.
4. Choose SQLite for one application instance or PostgreSQL for multiple
   instances. SQLite is not suitable for an active multi-replica website.
5. Expose the platform callback URL over HTTPS. Set
   `BRUNOST_PLATFORM_SESSION_COOKIE_SECURE=true`.

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
BRUNOST_JUDGE_API_TOKEN=<platform-service-token>
BRUNOST_PLATFORM_CALLBACK_URL=https://platform.example.org/api/judge/callback
BRUNOST_PLATFORM_CALLBACK_TOKEN=<random-bearer-token>
BRUNOST_JUDGE_CALLBACK_SECRET=<random-shared-signing-secret>
BRUNOST_PLATFORM_DATABASE=postgresql://platform:<password>@db.example/platform
BRUNOST_DEFAULT_ADMIN_EMAIL=admin@example.org
BRUNOST_DEFAULT_ADMIN_PASSWORD=<unique-temporary-password>
BRUNOST_PLATFORM_SESSION_COOKIE_SECURE=true
```

The callback signing secret must equal Judge's
`BRUNOST_JUDGE_CALLBACK_SIGNING_SECRET`. Keep both secrets outside source
control. Change the bootstrap password at first login.

## Publish a task and contest

An official task must be reviewed and tested before publishing. The production
flow is:

1. Scaffold a family-specific package with `brunost-platform task new`.
2. Complete the public statement/data, private assets, and evaluator.
3. Validate and upload the package with Judge, producing an immutable
   `artifact_id`.
4. Register a stable `task_ref` that points at that artifact.
5. A Platform administrator creates a contest and selects the registered task
   reference. The standalone UI does not publish task packages, administer
   workers, or operate Judge queues.

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
