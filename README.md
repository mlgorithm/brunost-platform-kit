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
Production integrations should use HTTPS. Optional `BRUNOST_JUDGE_CA_FILE`,
`BRUNOST_JUDGE_CLIENT_CERT_FILE`, and `BRUNOST_JUDGE_CLIENT_KEY_FILE` enable
private-CA verification and mTLS; authenticated redirects are rejected and
responses are bounded before JSON or artifact parsing.

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
export BRUNOST_DEFAULT_ADMIN_EMAIL=admin@example.org
export BRUNOST_DEFAULT_ADMIN_PASSWORD=change-me-now

uvicorn app.main:app --host 127.0.0.1 --port 3000
```

Open [http://127.0.0.1:3000](http://127.0.0.1:3000) for the reference landing
page, [http://127.0.0.1:3000/login](http://127.0.0.1:3000/login) to sign in, and
[http://127.0.0.1:3000/admin](http://127.0.0.1:3000/admin) for the operator
control room. The dashboard covers task packages, contests, workers,
evaluations, agent/game definitions, and platform-owned counts. The API remains
available at [http://127.0.0.1:3000/docs](http://127.0.0.1:3000/docs).

The application creates a temporary administrator automatically when the
database is empty. Sign in with `BRUNOST_DEFAULT_ADMIN_EMAIL` and
`BRUNOST_DEFAULT_ADMIN_PASSWORD`; the first-run screen requires you to replace
the temporary password before opening the dashboard. Set both values to unique
secrets before a shared or production deployment.

For an already-populated database, additional contestant accounts can still be
created through the registration endpoint:

```bash
curl -X POST http://127.0.0.1:3000/api/auth/register \
  -H 'content-type: application/json' \
  -d '{"email":"student@example.org","password":"change-this-password","display_name":"Contestant"}'
```

The generated pages are intentionally replaceable: countries can keep the
FastAPI routes, mount a separate frontend, or build another UI against the
same Platform Kit/Judge boundary.

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
For typed task registration, artifact-backed submission, evaluation requests,
and normalized result envelopes, see [`docs/contracts.md`](docs/contracts.md).
The kit includes a durable `SQLitePlatformStore` for local and standalone
deployments plus a shared `PostgresPlatformStore` for multi-instance
deployments. Select the PostgreSQL adapter by installing the optional extra and
using a PostgreSQL DSN; generated applications choose it automatically:

```bash
python -m pip install 'brunost-platform-kit[postgres]'
export BRUNOST_PLATFORM_DATABASE='postgresql://platform:password@db.example/platform'
```

The current PostgreSQL adapter stores the versioned platform document in one
transactionally locked JSONB row. That gives both app instances consistent
state while keeping the public contract stable; a future normalized schema can
replace the adapter without changing Judge integration. Installations can
start with SQLite and move to PostgreSQL or an external LMS without changing
the Judge contract.

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

## Standalone and Premium editions

The same open-source contest core can serve two deployment profiles. The
default standalone profile is a small national-contest website: the first
account is an administrator, later accounts are students, only administrators
create contests, and problems are authored inside a contest. It does not
remove Judge APIs or task capabilities; it keeps the optional global task
library out of the default operator UI.

Premium/advanced deployments keep that exact contest and Judge contract while
adding private modules such as organizations, courses, richer identity, and a
public task library. Enable the broader creator roles and optional UI with:

```bash
export BRUNOST_PLATFORM_EDITION=advanced
# Optional capability flags for a custom profile:
export BRUNOST_PLATFORM_FEATURES=task.global-library,courses,contest.user-created
```

The standalone default is explicit and safe to operate:

```bash
export BRUNOST_PLATFORM_EDITION=standalone
export BRUNOST_PLATFORM_FEATURES=
```

An embedded Premium application can keep its own authentication and pass an
opaque identity projection through `ExternalIdentityAdapter`. The adapter
accepts a subject, roles, organization, and metadata; passwords and external
tokens stay in the embedding application. This lets the existing Brunost UI
continue unchanged while it calls the shared contest/Judge APIs as a client.

See [`docs/editions.md`](docs/editions.md) for the ownership boundary and the
migration path from the reference UI to an existing platform.

The kit intentionally keeps its core dependency-free. Install framework
dependencies only in the generated application that needs them.

Install `brunost-platform-kit[judge]` when you want the canonical
`brunost-judge` SDK transport; otherwise the gateway uses its compatible
standard-library HTTP fallback.

For country-wide, no-code installation across control-plane and worker nodes,
use the companion [`brunost-deploy`](https://github.com/mlgorithm/brunost-deploy)
repository and its `brunostctl` CLI.
