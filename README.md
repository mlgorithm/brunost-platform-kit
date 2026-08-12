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
