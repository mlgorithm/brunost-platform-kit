# Brunost Platform Kit

The Platform Kit is the optional application layer above [Brunost Judge](https://github.com/mlgorithm/brunost-judge).
It provides a cohesive, framework-neutral developer experience without
requiring PHP, Laravel, or a specific frontend.

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

Judge callbacks are verified with `verify_judge_callback()` and then accepted
once with `SQLitePlatformStore.accept_callback_event(event_id)`. Use
`PlatformApplication.handle_callback()` in a framework route to automatically
update the submission and leaderboard projection.

Framework integrations are included under `integrations/`: `django-brunost`
provides models, migrations, admin, callback routes, and a doctor command;
`laravel-brunost` provides Composer service registration, migrations, Eloquent
models, Judge client, and callback routes.

## Integration modes

- **Standalone:** generated application plus a Brunost Judge deployment.
- **Embedded:** an existing LMS uses `HttpJudgeGateway` directly.
- **Hybrid:** generated modules are used with external identity, email, or
  leaderboard adapters.

The kit intentionally keeps its core dependency-free. Install framework
dependencies only in the generated application that needs them.
