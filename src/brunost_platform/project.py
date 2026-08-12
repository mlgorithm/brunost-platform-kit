"""Project templates used by the ``brunost-platform init`` command."""

from __future__ import annotations

from pathlib import Path

TEMPLATES = ("python-fastapi", "node-fastify", "minimal")
TASK_KINDS = ("agent", "game", "icpc", "interactive", "ioai", "ioi", "model", "output-only")


def _python_files(project_name: str) -> dict[str, str]:
    return {
        "README.md": f"""# {project_name}\n\nGenerated Brunost Platform Kit application.\n\n```bash\npython -m venv .venv && source .venv/bin/activate\npip install -e .\nuvicorn app.main:app --reload\n```\n\nSet `BRUNOST_JUDGE_URL` to the judge control plane. The platform owns users,\ncontest rules, and leaderboard policy; the judge owns execution and scoring.\n""",
        ".env.example": "BRUNOST_JUDGE_URL=http://127.0.0.1:8787\nBRUNOST_JUDGE_API_TOKEN=\nBRUNOST_JUDGE_IMAGE=ghcr.io/mlgorithm/brunost-judge@sha256:<64-hex-digest>\n",
        "pyproject.toml": """[project]\nname = \"brunost-platform-app\"\nversion = \"0.1.0\"\nrequires-python = \">=3.11\"\ndependencies = [\"fastapi>=0.115,<1\", \"uvicorn[standard]>=0.30,<1\", \"brunost-platform-kit>=0.1\"]\n\n[build-system]\nrequires = [\"setuptools>=68\"]\nbuild-backend = \"setuptools.build_meta\"\n""",
        "Dockerfile": """FROM python:3.12-slim\nWORKDIR /app\nCOPY . .\nRUN pip install --no-cache-dir .\nEXPOSE 3000\nCMD [\"uvicorn\", \"app.main:app\", \"--host\", \"0.0.0.0\", \"--port\", \"3000\"]\n""",
        "docker-compose.yml": """services:\n  platform:\n    build: .\n    ports: [\"3000:3000\"]\n    environment:\n      BRUNOST_JUDGE_URL: http://judge:8787\n    depends_on: [judge]\n  judge:\n    image: ${BRUNOST_JUDGE_IMAGE:?set BRUNOST_JUDGE_IMAGE to a digest-pinned image}\n    command: [\"brunost\", \"server\", \"--host\", \"0.0.0.0\", \"--port\", \"8787\"]\n    ports: [\"8787:8787\"]\n""",
        "app/__init__.py": "",
        "app/main.py": """from fastapi import FastAPI, HTTPException\nfrom pydantic import BaseModel, Field\n\nfrom brunost_platform.gateway import gateway_from_environment\n\napp = FastAPI(title=\"Brunost Platform\")\njudge = gateway_from_environment()\n\n\nclass EvaluationIn(BaseModel):\n    task_ref: str = Field(min_length=1)\n    submission_path: str = Field(min_length=1)\n    idempotency_key: str = Field(min_length=1)\n    evaluation_kind: str = \"batch\"\n    agent_refs: list[str] = []\n    game_ref: str | None = None\n    seed: int | None = None\n\n\n@app.get(\"/healthz\")\ndef health():\n    try:\n        return {\"status\": \"ok\", \"judge\": judge.health()}\n    except Exception as exc:\n        raise HTTPException(status_code=503, detail=str(exc)) from exc\n\n\n@app.post(\"/api/evaluations\", status_code=202)\ndef submit_evaluation(request: EvaluationIn):\n    return judge.submit_evaluation(**request.model_dump())\n\n\n@app.get(\"/api/evaluations/{evaluation_id}\")\ndef get_evaluation(evaluation_id: str):\n    return judge.get_evaluation(evaluation_id)\n""",
        "tasks/hello/judge.yaml": """version: 1\nkind: ioai\nruntime: python-3.13\nscoring: scorer.metrics:evaluate\nnetwork: disabled\n""",
        "tasks/hello/scorer/metrics.py": """def evaluate(submission_path: str, assets_path: str) -> dict[str, float]:\n    _ = submission_path, assets_path\n    return {\"public\": 0.0}\n""",
        "tasks/hello/public/README.md": "Put contestant-visible files here.\n",
        "tasks/hello/private/.gitkeep": "",
    }


def _node_files(project_name: str) -> dict[str, str]:
    return {
        "README.md": f"""# {project_name}\n\nGenerated Brunost Platform Kit application using Node.js and Fastify.\n\n```bash\nnpm install\nnpm run dev\n```\n""",
        ".env.example": "BRUNOST_JUDGE_URL=http://127.0.0.1:8787\nBRUNOST_JUDGE_API_TOKEN=\n",
        "package.json": """{\n  \"name\": \"brunost-platform-app\",\n  \"private\": true,\n  \"type\": \"module\",\n  \"scripts\": {\"dev\": \"tsx watch src/server.ts\", \"start\": \"tsx src/server.ts\"},\n  \"dependencies\": {\"@fastify/cors\": \"^10.0.0\", \"fastify\": \"^5.0.0\"},\n  \"devDependencies\": {\"tsx\": \"^4.0.0\", \"typescript\": \"^5.0.0\"}\n}\n""",
        "src/server.ts": """import Fastify from \"fastify\";\n\nconst app = Fastify({ logger: true });\nconst judgeUrl = process.env.BRUNOST_JUDGE_URL ?? \"http://127.0.0.1:8787\";\nconst token = process.env.BRUNOST_JUDGE_API_TOKEN;\n\napp.get(\"/healthz\", async () => {\n  const response = await fetch(`${judgeUrl}/healthz`);\n  return { status: \"ok\", judge: await response.json() };\n});\n\napp.post(\"/api/evaluations\", async (request, reply) => {\n  const response = await fetch(`${judgeUrl}/v1/evaluations`, {\n    method: \"POST\",\n    headers: { \"content-type\": \"application/json\", ...(token ? { authorization: `Bearer ${token}` } : {}) },\n    body: JSON.stringify(request.body),\n  });\n  reply.code(response.status);\n  return response.json();\n});\n\napp.listen({ port: Number(process.env.PORT ?? 3000), host: \"0.0.0.0\" });\n""",
        "tsconfig.json": """{\n  \"compilerOptions\": {\"target\": \"ES2022\", \"module\": \"NodeNext\", \"moduleResolution\": \"NodeNext\", \"strict\": true, \"esModuleInterop\": true}\n}\n""",
    }


def _minimal_files(project_name: str) -> dict[str, str]:
    return {
        "README.md": f"# {project_name}\n\nFramework-neutral Brunost application skeleton.\n",
        ".env.example": "BRUNOST_JUDGE_URL=http://127.0.0.1:8787\nBRUNOST_JUDGE_API_TOKEN=\n",
        "brunost.yaml": "version: 1\njudge:\n  url: ${BRUNOST_JUDGE_URL}\nmodules:\n  identity: external\n  leaderboard: external\n  notifications: external\n",
        "tasks/hello/judge.yaml": "version: 1\nkind: ioai\nruntime: python-3.13\nscoring: scorer.metrics:evaluate\nnetwork: disabled\n",
    }


def template_files(template: str, project_name: str) -> dict[str, str]:
    if template == "python-fastapi":
        files = _python_files(project_name)
        files["app/main.py"] = files["app/main.py"].replace(
            "from fastapi import FastAPI, HTTPException\nfrom pydantic import BaseModel, Field\n\nfrom brunost_platform.gateway import gateway_from_environment",
            "import os\n\nfrom fastapi import FastAPI, HTTPException\nfrom pydantic import BaseModel, Field\n\nfrom brunost_platform.application import PlatformApplication\nfrom brunost_platform.gateway import gateway_from_environment\nfrom brunost_platform.models import Contest, Submission\nfrom brunost_platform.store import SQLitePlatformStore",
        )
        files["app/main.py"] = files["app/main.py"].replace(
            "judge = gateway_from_environment()",
            "judge = gateway_from_environment()\nstore = SQLitePlatformStore(os.environ.get(\"BRUNOST_PLATFORM_DATABASE\", \"platform.db\"))\nplatform = PlatformApplication(judge, store=store)",
        )
        files["app/main.py"] = files["app/main.py"].replace(
            "    evaluation_kind: str = \"batch\"\n",
            "    evaluation_kind: str = \"batch\"\n    contestant_id: str = \"anonymous\"\n    contest_id: str | None = None\n",
        )
        files["app/main.py"] = files["app/main.py"].replace(
            "    return judge.submit_evaluation(**request.model_dump())",
            "    submission = Submission(request.idempotency_key, request.contestant_id, request.task_ref, request.submission_path, request.contest_id)\n    return platform.submit(submission, evaluation_kind=request.evaluation_kind, agent_refs=request.agent_refs, game_ref=request.game_ref, seed=request.seed)",
        )
        files["app/main.py"] += """\n\nclass ContestIn(BaseModel):\n    contest_id: str = Field(min_length=1)\n    name: str = Field(min_length=1)\n    task_refs: list[str] = Field(default_factory=list)\n\n\n@app.post(\"/api/contests\", status_code=201)\ndef create_contest(request: ContestIn):\n    return platform.create_contest(Contest(request.contest_id, request.name, tuple(request.task_refs))).as_dict()\n\n\n@app.get(\"/api/contests\")\ndef list_contests():\n    return [contest.as_dict() for contest in store.list_contests()]\n"""
        return files
    if template == "node-fastify":
        return _node_files(project_name)
    if template == "minimal":
        return _minimal_files(project_name)
    raise ValueError(f"unknown template {template!r}; choose one of {', '.join(TEMPLATES)}")


def create_project(path: str | Path, *, template: str, force: bool = False) -> Path:
    root = Path(path).expanduser().resolve()
    if root.exists() and any(root.iterdir()) and not force:
        raise FileExistsError(f"refusing to overwrite non-empty directory: {root}")
    root.mkdir(parents=True, exist_ok=True)
    name = root.name
    for relative, contents in template_files(template, name).items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not force:
            raise FileExistsError(f"refusing to overwrite {target}")
        target.write_text(contents, encoding="utf-8")
    return root


def create_task(path: str | Path, *, kind: str = "ioai", force: bool = False) -> Path:
    """Create a portable task package without requiring a web framework."""
    if kind not in TASK_KINDS:
        raise ValueError(f"unknown task kind {kind!r}; choose one of {', '.join(TASK_KINDS)}")
    root = Path(path).expanduser().resolve()
    if root.exists() and any(root.iterdir()) and not force:
        raise FileExistsError(f"refusing to overwrite non-empty directory: {root}")
    files = {
        "judge.yaml": f"version: 1\nkind: {kind}\nruntime: python-3.13\nscoring: scorer.metrics:evaluate\nnetwork: disabled\n",
        "scorer/metrics.py": "def evaluate(submission_path: str, assets_path: str) -> dict[str, float]:\n    _ = submission_path, assets_path\n    return {'public': 0.0}\n",
        "public/README.md": "Put contestant-visible files here.\n",
        "private/.gitkeep": "",
        "tests/test_task.py": "# Add deterministic scorer tests here.\n",
    }
    root.mkdir(parents=True, exist_ok=True)
    for relative, contents in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not force:
            raise FileExistsError(f"refusing to overwrite {target}")
        target.write_text(contents, encoding="utf-8")
    return root


def create_contest(path: str | Path, *, contest_id: str | None = None, force: bool = False) -> Path:
    """Create a platform-owned contest descriptor."""
    root = Path(path).expanduser().resolve()
    if root.exists() and any(root.iterdir()) and not force:
        raise FileExistsError(f"refusing to overwrite non-empty directory: {root}")
    root.mkdir(parents=True, exist_ok=True)
    identifier = contest_id or root.name
    (root / "contest.yaml").write_text(
        f"version: 1\nid: {identifier}\nstatus: draft\ntasks: []\nleaderboard: hidden\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text(
        "# Contest\n\nAdd task references and platform-specific registration rules here.\n",
        encoding="utf-8",
    )
    return root
