# Contributing to Brunost Platform Kit

The Platform Kit is intentionally framework-neutral. Contributions should keep
the judge gateway independent from FastAPI, Node.js, ORM, cloud, or identity
providers.

Before opening a pull request:

```bash
uv sync --extra dev
uv run pytest -q
uv run ruff check src tests
uv build --wheel --sdist
```

New adapters should implement a small protocol, include a fake/in-memory test,
and document which part of the platform they own. Do not add user, contest, or
leaderboard tables to the judge repository.
