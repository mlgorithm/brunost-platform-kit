# Brunost Platform Kit

The Platform Kit is the optional Python application layer above [Brunost Judge](https://github.com/mlgorithm/brunost-judge).
It provides a cohesive FastAPI-first developer experience without coupling the
Judge to a specific frontend or country platform.

## Quick start

```bash
python -m pip install -e '.[dev]'
brunost-platform templates
brunost-platform init my-country --template python-fastapi
cd my-country
```

The same CLI scaffolds portable tasks and platform-owned contests:

```bash
brunost-platform task new tasks/radar --kind ioai
brunost-platform contest new contests/national-final --id national-final
brunost-platform doctor
```

## Run the reference FastAPI UI locally

The generated FastAPI application is the maintained reference UI/API. It runs
separately from the Judge and connects to it through `BRUNOST_JUDGE_URL`.

First start a Judge API and at least one worker using the Judge's
[`local-worker-smoke-test.md`](https://github.com/mlgorithm/brunost-judge/blob/main/docs/local-worker-smoke-test.md).
When callbacks are enabled, set the Judge's
`BRUNOST_JUDGE_CALLBACK_SIGNING_SECRET` to the same value used below for
`BRUNOST_JUDGE_CALLBACK_SECRET`.
Then create and run the platform application:

```bash
cd /Users/sam.urmian/Documents/github/brunost-platform-kit
python3 -m venv .venv-platform
source .venv-platform/bin/activate
python -m pip install -e .
python -m pip install -e /Users/sam.urmian/Documents/github/brunost-judge

brunost-platform init /tmp/brunost-ui --template python-fastapi
cd /tmp/brunost-ui
python -m pip install -e .

export BRUNOST_JUDGE_URL=http://127.0.0.1:8799
export BRUNOST_JUDGE_API_TOKEN=local-admin-token
export BRUNOST_JUDGE_CALLBACK_SECRET=local-callback-secret
export BRUNOST_PLATFORM_CALLBACK_TOKEN=local-platform-callback-token
export BRUNOST_PLATFORM_CALLBACK_URL=http://127.0.0.1:3000/api/judge/callback
export BRUNOST_PLATFORM_DATABASE="$PWD/platform.db"
export BRUNOST_SUBMISSION_ROOT="$PWD/submissions"

uvicorn app.main:app --host 127.0.0.1 --port 3000
```

Open [http://127.0.0.1:3000](http://127.0.0.1:3000) for the reference pages
and [http://127.0.0.1:3000/docs](http://127.0.0.1:3000/docs) for the API.
The starter exposes JSON authentication and submission endpoints; its HTML
pages are intentionally small so countries can replace them with their own
frontend while keeping the same Platform Kit/Judge boundary.

For a published package, install `brunost-platform-kit` from its release
instead of the editable source path. The generated application still needs a
Judge URL, API token, callback secret, and a database location.

Available templates:

- `python-fastapi` — a batteries-included Python API starter.
- `node-fastify` — a Node.js/TypeScript starter using Fastify.
- `minimal` — framework-neutral configuration and task skeleton.

Generated applications own users, contests, notifications, and leaderboard
policy. They call the judge through the stable `JudgeGateway`; the judge owns
sandbox execution, scoring, scheduling, and worker operations.

The kit uploads every submission as a deterministic, content-addressed artifact
before calling the Judge; filesystem paths never cross the service boundary.
The kit also includes a durable `SQLitePlatformStore` for standalone deployments
and replaceable identity, notification, and leaderboard adapters. Installations
can start with SQLite and move to their preferred database or external LMS
without changing the judge contract.

Judge callbacks are verified with `verify_judge_callback()` and processed by a
durable receipt state machine (`applying` → `applied`, with failed claims
retryable). Use `PlatformApplication.handle_callback()` in a framework route
to transactionally update the submission, leaderboard projection, audit row,
and receipt. `SQLitePlatformStore` applies the shared versioned leaderboard
policy for visibility, freezes, aggregation, and deterministic ties.

The Django package under `integrations/django-brunost` provides models,
migrations, admin, callback routes, submissions, leaderboard projection, and a
doctor command. FastAPI is the maintained reference application; other Python
frameworks can use the same dependency-free gateway and contracts.

## Integration modes

- **Standalone:** generated application plus a Brunost Judge deployment.
- **Embedded:** an existing LMS uses `HttpJudgeGateway` directly.
- **Hybrid:** generated modules are used with external identity, email, or
  leaderboard adapters.

The kit intentionally keeps its core dependency-free. Install framework
dependencies only in the generated application that needs them.

Install `brunost-platform-kit[judge]` when you want the canonical
`brunost-judge` SDK transport; otherwise the gateway uses its compatible
standard-library HTTP fallback.

For country-wide, no-code installation across control-plane and worker nodes,
use the companion [`brunost-deploy`](https://github.com/mlgorithm/brunost-deploy)
repository and its `brunostctl` CLI.
