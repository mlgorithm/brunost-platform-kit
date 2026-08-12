"""Project templates used by the ``brunost-platform init`` command."""

from __future__ import annotations

from pathlib import Path

TEMPLATES = ("python-fastapi", "node-fastify", "minimal")
TASK_KINDS = ("agent", "game", "icpc", "interactive", "ioai", "ioi", "model", "output-only")


def _reference_fastapi_main() -> str:
    """A small, real platform flow used by the generated reference app."""
    return '''from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from brunost_platform.application import PlatformApplication
from brunost_platform.gateway import gateway_from_environment
from brunost_platform.identity import LocalIdentityAdapter
from brunost_platform.models import Contest, Submission
from brunost_platform.store import SQLitePlatformStore


app = FastAPI(title="Brunost Competition Platform")
store = SQLitePlatformStore(os.environ.get("BRUNOST_PLATFORM_DATABASE", "platform.db"))
judge = gateway_from_environment()
platform = PlatformApplication(judge, store=store)
identity = LocalIdentityAdapter(store)
submission_root = Path(os.environ.get("BRUNOST_SUBMISSION_ROOT", "submissions")).expanduser().resolve()
callback_url = os.environ.get("BRUNOST_PLATFORM_CALLBACK_URL", "http://127.0.0.1:3000/api/judge/callback")


class RegisterIn(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=10)
    display_name: str = Field(min_length=1, max_length=120)


class LoginIn(BaseModel):
    email: str
    password: str


class ContestIn(BaseModel):
    contest_id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=200)
    task_refs: list[str] = Field(default_factory=list)
    leaderboard_visible: bool = False
    best_attempt: bool = True


def current_user(authorization: str | None = Header(default=None)):
    token = authorization.removeprefix("Bearer ").strip() if authorization else ""
    user = store.get_session_user(token) if token else None
    if user is None:
        raise HTTPException(status_code=401, detail="login required")
    return user


def staff_user(user=Depends(current_user)):
    if not set(user.roles).intersection({"admin", "organizer"}):
        raise HTTPException(status_code=403, detail="organizer privileges required")
    return user


@app.get("/healthz")
def health():
    return {"status": "ok", "judge": judge.health()}


@app.post("/api/auth/register", status_code=201)
def register(request: RegisterIn):
    if store.get_user_by_email(request.email):
        raise HTTPException(status_code=409, detail="email is already registered")
    # The first account is the local administrator so a fresh standalone
    # deployment can create its first contest without editing the database.
    roles = ("admin",) if not store.list_users() else ("contestant",)
    return identity.register(email=request.email, password=request.password, display_name=request.display_name, roles=roles).as_dict()


@app.post("/api/auth/login")
def login(request: LoginIn):
    token = identity.authenticate(email=request.email, password=request.password)
    if not token:
        raise HTTPException(status_code=401, detail="invalid credentials")
    return {"access_token": token, "token_type": "bearer"}


@app.get("/api/me")
def me(user=Depends(current_user)):
    return user.as_dict()


@app.post("/api/contests", status_code=201)
def create_contest(request: ContestIn, user=Depends(staff_user)):
    return platform.create_contest(Contest(request.contest_id, request.name, tuple(request.task_refs), metadata={"leaderboard_visible": request.leaderboard_visible, "best_attempt": request.best_attempt})).as_dict()


@app.get("/api/contests")
def list_contests():
    return [contest.as_dict() for contest in store.list_contests()]


@app.post("/api/contests/{contest_id}/register")
def register_for_contest(contest_id: str, user=Depends(current_user)):
    if store.get_contest(contest_id) is None:
        raise HTTPException(status_code=404, detail="contest not found")
    store.register_contestant(contest_id, user.user_id)
    return {"contest_id": contest_id, "user_id": user.user_id, "registered": True}


@app.post("/api/contests/{contest_id}/submit", status_code=202)
async def submit(contest_id: str, task_ref: str = Form(...), file: UploadFile = File(...), user=Depends(current_user)):
    contest = store.get_contest(contest_id)
    if contest is None:
        raise HTTPException(status_code=404, detail="contest not found")
    if task_ref not in contest.task_refs:
        raise HTTPException(status_code=422, detail="task is not part of this contest")
    if not store.is_registered(contest_id, user.user_id):
        raise HTTPException(status_code=403, detail="register for the contest first")
    submission_id = str(uuid.uuid4())
    target_dir = submission_root / submission_id
    target_dir.mkdir(parents=True, exist_ok=False)
    filename = Path(file.filename or "submission.bin").name
    if filename in {"", ".", ".."}:
        filename = "submission.bin"
    target = target_dir / filename
    with target.open("wb") as output:
        shutil.copyfileobj(file.file, output)
    submission = Submission(submission_id, user.user_id, task_ref, str(target_dir), contest_id)
    return platform.submit(submission, callback_url=callback_url, callback_token=os.environ.get("BRUNOST_PLATFORM_CALLBACK_TOKEN"))


@app.get("/api/submissions")
def submissions(user=Depends(current_user)):
    return [submission.as_dict() for submission in store.list_submissions(contestant_id=user.user_id)]


@app.post("/api/judge/callback")
async def judge_callback(request: Request):
    try:
        return platform.handle_callback(await request.body(), dict(request.headers))
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/contests/{contest_id}/leaderboard")
def leaderboard(contest_id: str):
    return [entry.as_dict() for entry in store.list_leaderboard(contest_id)]


@app.get("/", response_class=HTMLResponse)
def home():
    return """<!doctype html><title>Brunost Platform</title><h1>Brunost Platform</h1>
    <p>Platform-owned identity, contests, submissions, and leaderboard projections.</p>
    <p><a href='/contests'>Browse contests</a> · <a href='/profile'>Profile</a></p>"""


@app.get("/contests", response_class=HTMLResponse)
def contest_page():
    rows = "".join(f"<li><a href='/contests/{contest.contest_id}'>{contest.name}</a></li>" for contest in store.list_contests())
    return f"<!doctype html><title>Contests</title><h1>Contests</h1><ul>{rows}</ul>"


@app.get("/contests/{contest_id}", response_class=HTMLResponse)
def contest_detail_page(contest_id: str):
    contest = store.get_contest(contest_id)
    if contest is None:
        raise HTTPException(status_code=404, detail="contest not found")
    leaderboard = store.list_leaderboard(contest_id)
    rows = "".join(f"<tr><td>{entry.metadata.get('rank', '')}</td><td>{entry.contestant_id}</td><td>{entry.score}</td></tr>" for entry in leaderboard)
    return f"<!doctype html><title>{contest.name}</title><h1>{contest.name}</h1><h2>Leaderboard</h2><table><tr><th>Rank</th><th>Contestant</th><th>Score</th></tr>{rows}</table>"


@app.get("/profile", response_class=HTMLResponse)
def profile_page():
    return "<!doctype html><title>Profile</title><h1>Profile</h1><p>Use the JSON auth endpoints to log in and submit.</p>"
'''


def _python_files(project_name: str) -> dict[str, str]:
    return {
        "README.md": f"""# {project_name}\n\nGenerated Brunost Platform Kit application.\n\n```bash\npython -m venv .venv && source .venv/bin/activate\npip install -e .\nuvicorn app.main:app --reload\n```\n\nSet `BRUNOST_JUDGE_URL` to the judge control plane. The platform owns users,\ncontest rules, and leaderboard policy; the judge owns execution and scoring.\n""",
        ".env.example": "BRUNOST_JUDGE_URL=http://127.0.0.1:8787\nBRUNOST_JUDGE_API_TOKEN=\nBRUNOST_JUDGE_IMAGE=ghcr.io/mlgorithm/brunost-judge@sha256:<64-hex-digest>\nBRUNOST_JUDGE_CALLBACK_SECRET=replace-with-judge-callback-secret\nBRUNOST_PLATFORM_CALLBACK_URL=http://127.0.0.1:3000/api/judge/callback\nBRUNOST_PLATFORM_CALLBACK_TOKEN=replace-with-callback-token\n",
        "pyproject.toml": """[project]\nname = \"brunost-platform-app\"\nversion = \"0.1.0\"\nrequires-python = \">=3.11\"\ndependencies = [\"fastapi>=0.115,<1\", \"uvicorn[standard]>=0.30,<1\", \"python-multipart>=0.0.9,<1\", \"brunost-platform-kit>=0.1\"]\n\n[build-system]\nrequires = [\"setuptools>=68\"]\nbuild-backend = \"setuptools.build_meta\"\n""",
        "Dockerfile": """FROM python:3.12-slim\nWORKDIR /app\nCOPY . .\nRUN pip install --no-cache-dir .\nEXPOSE 3000\nCMD [\"uvicorn\", \"app.main:app\", \"--host\", \"0.0.0.0\", \"--port\", \"3000\"]\n""",
        "docker-compose.yml": """services:\n  platform:\n    build: .\n    ports: [\"3000:3000\"]\n    environment:\n      BRUNOST_JUDGE_URL: http://judge:8787\n      BRUNOST_PLATFORM_CALLBACK_URL: http://platform:3000/api/judge/callback\n      BRUNOST_PLATFORM_CALLBACK_TOKEN: ${BRUNOST_PLATFORM_CALLBACK_TOKEN:?set a callback bearer token}\n      BRUNOST_JUDGE_CALLBACK_SECRET: ${BRUNOST_JUDGE_CALLBACK_SECRET:?set a callback signing secret}\n    depends_on: [judge]\n  judge:\n    image: ${BRUNOST_JUDGE_IMAGE:?set BRUNOST_JUDGE_IMAGE to a digest-pinned image}\n    command: [\"brunost\", \"server\", \"--host\", \"0.0.0.0\", \"--port\", \"8787\"]\n    environment:\n      BRUNOST_JUDGE_CALLBACK_SIGNING_SECRET: ${BRUNOST_JUDGE_CALLBACK_SECRET:?set a callback signing secret}\n      BRUNOST_JUDGE_CALLBACK_HOSTS: platform\n    ports: [\"8787:8787\"]\n""",
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
        ".env.example": "BRUNOST_JUDGE_URL=http://127.0.0.1:8787\nBRUNOST_JUDGE_API_TOKEN=\nBRUNOST_JUDGE_CALLBACK_SECRET=replace-with-judge-callback-secret\nBRUNOST_PLATFORM_CALLBACK_URL=http://127.0.0.1:3000/api/judge/callback\nBRUNOST_PLATFORM_CALLBACK_TOKEN=replace-with-callback-token\nBRUNOST_PLATFORM_DATABASE=platform.json\n",
        "package.json": """{\n  \"name\": \"brunost-platform-app\",\n  \"private\": true,\n  \"type\": \"module\",\n  \"scripts\": {\"dev\": \"tsx watch src/server.ts\", \"start\": \"tsx src/server.ts\", \"typecheck\": \"tsc --noEmit\"},\n  \"dependencies\": {\"@fastify/cors\": \"^10.0.0\", \"@fastify/multipart\": \"^9.0.0\", \"fastify\": \"^5.0.0\", \"tar\": \"^7.4.3\"},\n  \"devDependencies\": {\"tsx\": \"^4.0.0\", \"typescript\": \"^5.0.0\", \"@types/node\": \"^22.0.0\"}\n}\n""",
        "src/server.ts": """import Fastify, { FastifyReply, FastifyRequest } from \"fastify\";\nimport cors from \"@fastify/cors\";\nimport multipart from \"@fastify/multipart\";\nimport { createHash, createHmac, randomBytes, randomUUID, scryptSync, timingSafeEqual } from \"node:crypto\";\nimport { createWriteStream } from \"node:fs\";\nimport { mkdir, readFile, writeFile } from \"node:fs/promises\";\nimport { pipeline } from \"node:stream/promises\";\nimport { join } from \"node:path\";\nimport tar from \"tar\";\n\ntype User = { id: string; email: string; displayName: string; roles: string[]; salt: string; passwordHash: string };\ntype Contest = { id: string; name: string; taskRefs: string[]; policy: { leaderboardVisible?: boolean; bestAttempt?: boolean } };\ntype Submission = { id: string; userId: string; contestId: string; taskRef: string; artifactId?: string; evaluationId?: string; status: string; score?: number; metrics?: Record<string, number> };\ntype State = { users: User[]; contests: Contest[]; registrations: string[]; submissions: Submission[]; leaderboard: Submission[]; events: string[]; sessions: Record<string, { userId: string; expiresAt: number }> };\n\nconst app = Fastify({ logger: true });\nconst judgeUrl = process.env.BRUNOST_JUDGE_URL ?? \"http://127.0.0.1:8787\";\nconst judgeToken = process.env.BRUNOST_JUDGE_API_TOKEN;\nconst callbackSecret = process.env.BRUNOST_JUDGE_CALLBACK_SECRET ?? \"\";\nconst callbackToken = process.env.BRUNOST_PLATFORM_CALLBACK_TOKEN ?? \"\";\nconst statePath = process.env.BRUNOST_PLATFORM_DATABASE ?? \"platform.json\";\nconst submissionRoot = join(process.cwd(), \"submissions\");\nlet state: State = { users: [], contests: [], registrations: [], submissions: [], leaderboard: [], events: [], sessions: {} };\n\nasync function loadState() { try { state = JSON.parse(await readFile(statePath, \"utf8\")) as State; } catch { await saveState(); } }\nasync function saveState() { await writeFile(statePath, JSON.stringify(state, null, 2)); }\nfunction auth(request: FastifyRequest, reply: FastifyReply): User | undefined {\n  const token = String(request.headers.authorization ?? \"\").replace(/^Bearer\\s+/i, \"\");\n  const session = state.sessions[token];\n  const user = session && session.expiresAt > Date.now() ? state.users.find((candidate) => candidate.id === session.userId) : undefined;\n  if (!user) { void reply.code(401).send({ detail: \"login required\" }); return undefined; }\n  return user;\n}\nfunction staff(user: User, reply: FastifyReply): boolean {\n  if (!user.roles.some((role) => role === \"admin\" || role === \"organizer\")) { void reply.code(403).send({ detail: \"organizer privileges required\" }); return false; }\n  return true;\n}\nasync function judge(path: string, init: RequestInit = {}) {\n  const headers = new Headers(init.headers); headers.set(\"accept\", \"application/json\");\n  if (judgeToken) headers.set(\"authorization\", `Bearer ${judgeToken}`);\n  const response = await fetch(`${judgeUrl}${path}`, { ...init, headers });\n  if (!response.ok) throw new Error(`Judge API returned ${response.status}: ${await response.text()}`);\n  return response.json();\n}\nasync function packageSubmission(directory: string): Promise<{ id: string; data: Buffer }> {\n  const data = Buffer.from(await tar.c({ cwd: directory, gzip: true, portable: true, mtime: new Date(0) }, [\".\"]));\n  return { id: createHash(\"sha256\").update(data).digest(\"hex\"), data };\n}\n\nawait loadState();\nawait app.register(cors);\nawait app.register(multipart);\napp.get(\"/healthz\", async () => ({ status: \"ok\", judge: await judge(\"/healthz\") }));\napp.post(\"/api/auth/register\", async (request, reply) => {\n  const body = request.body as { email: string; password: string; displayName: string };\n  if (!body.email || !body.password || body.password.length < 10) return reply.code(422).send({ detail: \"email and a 10+ character password are required\" });\n  if (state.users.some((user) => user.email === body.email.toLowerCase())) return reply.code(409).send({ detail: \"email is already registered\" });\n  const salt = randomBytes(16).toString(\"hex\");\n  const user: User = { id: randomUUID(), email: body.email.toLowerCase(), displayName: body.displayName, roles: state.users.length ? [\"contestant\"] : [\"admin\"], salt, passwordHash: scryptSync(body.password, salt, 64).toString(\"hex\") };\n  state.users.push(user); await saveState(); return reply.code(201).send({ id: user.id, email: user.email, displayName: user.displayName, roles: user.roles });\n});\napp.post(\"/api/auth/login\", async (request, reply) => {\n  const body = request.body as { email: string; password: string }; const user = state.users.find((candidate) => candidate.email === body.email.toLowerCase());\n  if (!user) return reply.code(401).send({ detail: \"invalid credentials\" });\n  const actual = scryptSync(body.password, user.salt, 64); const expected = Buffer.from(user.passwordHash, \"hex\");\n  if (actual.length !== expected.length || !timingSafeEqual(actual, expected)) return reply.code(401).send({ detail: \"invalid credentials\" });\n  const token = randomBytes(32).toString(\"base64url\"); state.sessions[token] = { userId: user.id, expiresAt: Date.now() + 86_400_000 }; await saveState(); return { accessToken: token, tokenType: \"bearer\" };\n});\napp.get(\"/api/me\", async (request, reply) => { const user = auth(request, reply); return user && { id: user.id, email: user.email, displayName: user.displayName, roles: user.roles }; });\napp.post(\"/api/contests\", async (request, reply) => { const user = auth(request, reply); if (!user || !staff(user, reply)) return; const body = request.body as { id: string; name: string; taskRefs: string[]; policy?: Contest[\"policy\"] }; const contest: Contest = { id: body.id, name: body.name, taskRefs: body.taskRefs ?? [], policy: body.policy ?? {} }; state.contests.push(contest); await saveState(); return reply.code(201).send(contest); });\napp.get(\"/api/contests\", async () => state.contests);\napp.post(\"/api/contests/:contestId/register\", async (request, reply) => { const user = auth(request, reply); if (!user) return; const contestId = (request.params as { contestId: string }).contestId; if (!state.contests.some((contest) => contest.id === contestId)) return reply.code(404).send({ detail: \"contest not found\" }); const key = `${contestId}:${user.id}`; if (!state.registrations.includes(key)) state.registrations.push(key); await saveState(); return { registered: true, contestId }; });\napp.post(\"/api/contests/:contestId/submit\", async (request, reply) => {\n  const user = auth(request, reply); if (!user) return; const contestId = (request.params as { contestId: string }).contestId; const contest = state.contests.find((candidate) => candidate.id === contestId); if (!contest) return reply.code(404).send({ detail: \"contest not found\" });\n  if (!state.registrations.includes(`${contestId}:${user.id}`)) return reply.code(403).send({ detail: \"register for the contest first\" });\n  const part = await (request as FastifyRequest & { file: () => Promise<any> }).file(); const taskRef = String(part?.fields?.task_ref?.value ?? \"\"); if (!part || !contest.taskRefs.includes(taskRef)) return reply.code(422).send({ detail: \"task_ref is not part of the contest\" });\n  const submissionId = randomUUID(); const directory = join(submissionRoot, submissionId); await mkdir(directory, { recursive: true }); await pipeline(part.file, createWriteStream(join(directory, part.filename || \"submission.bin\")));\n  const artifact = await packageSubmission(directory); const upload = await fetch(`${judgeUrl}/v1/artifacts/${artifact.id}`, { method: \"PUT\", body: artifact.data, headers: { \"content-type\": \"application/gzip\", ...(judgeToken ? { authorization: `Bearer ${judgeToken}` } : {}) } }); if (!upload.ok) throw new Error(`artifact upload failed: ${upload.status}`);\n  const submission: Submission = { id: submissionId, userId: user.id, contestId, taskRef, artifactId: artifact.id, status: \"queued\" }; state.submissions.push(submission); await saveState();\n  const result = await judge(\"/v1/evaluations\", { method: \"POST\", headers: { \"content-type\": \"application/json\" }, body: JSON.stringify({ task_ref: taskRef, submission_artifact_id: artifact.id, idempotency_key: submissionId, callback_url: process.env.BRUNOST_PLATFORM_CALLBACK_URL ?? \"http://127.0.0.1:3000/api/judge/callback\", callback_token: callbackToken, metadata: { platform_submission_id: submissionId, contestant_id: user.id, contest_id: contestId } }) }); submission.evaluationId = result.evaluation_id ?? result.execution_id; await saveState(); return reply.code(202).send(result);\n});\napp.get(\"/api/submissions\", async (request, reply) => { const user = auth(request, reply); return user ? state.submissions.filter((submission) => submission.userId === user.id) : undefined; });\napp.post(\"/api/judge/callback\", async (request, reply) => {\n  const raw = JSON.stringify(request.body); const eventId = String(request.headers[\"x-brunost-judge-event-id\"] ?? \"\"); const timestamp = String(request.headers[\"x-brunost-judge-timestamp\"] ?? \"\"); const signature = String(request.headers[\"x-brunost-judge-signature\"] ?? \"\");\n  if (callbackToken && request.headers.authorization !== `Bearer ${callbackToken}`) return reply.code(401).send({ detail: \"invalid callback bearer token\" });\n  const expected = `sha256=${createHmac(\"sha256\", callbackSecret).update(`${timestamp}.${eventId}.${raw}`).digest(\"hex\")}`; if (!eventId || Math.abs(Date.now() / 1000 - Number(timestamp)) > 300 || signature !== expected) return reply.code(401).send({ detail: \"invalid callback signature\" });\n  if (state.events.includes(eventId)) return { status: \"duplicate\", eventId }; state.events.push(eventId); const payload = request.body as any; const submission = state.submissions.find((candidate) => candidate.id === payload.metadata?.platform_submission_id); if (!submission) return reply.code(404).send({ detail: \"unknown submission\" }); submission.status = payload.status ?? \"failed\"; submission.score = payload.score; submission.metrics = payload.metrics ?? {}; submission.evaluationId = payload.evaluation_id ?? payload.execution_id; state.leaderboard.push({ ...submission }); await saveState(); return { status: submission.status, eventId };\n});\napp.get(\"/api/contests/:contestId/leaderboard\", async (request) => { const contestId = (request.params as { contestId: string }).contestId; const contest = state.contests.find((candidate) => candidate.id === contestId); const entries = state.leaderboard.filter((submission) => submission.contestId === contestId && (contest?.policy.leaderboardVisible ?? false)); const best = new Map<string, Submission>(); for (const entry of entries) { const key = `${entry.userId}:${entry.taskRef}`; if (!best.has(key) || (entry.score ?? -Infinity) > (best.get(key)?.score ?? -Infinity)) best.set(key, entry); } return [...best.values()].sort((a, b) => (b.score ?? -Infinity) - (a.score ?? -Infinity)); });\n\nawait app.listen({ port: Number(process.env.PORT ?? 3000), host: \"0.0.0.0\" });\n""",
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
        files["app/main.py"] = _reference_fastapi_main()
        return files
    if template == "node-fastify":
        files = _node_files(project_name)
        files["src/server.ts"] = files["src/server.ts"].replace('import tar from "tar";', 'import * as tar from "tar";')
        files["package.json"] = files["package.json"].replace(
            '\"fastify\": \"^5.0.0\",',
            '\"fastify\": \"^5.0.0\", \"fastify-raw-body\": \"^5.0.0\",',
        )
        files["src/server.ts"] = files["src/server.ts"].replace(
            "part?.fields?.task_ref?.value",
            "(part?.fields as any)?.task_ref?.value",
        )
        files["src/server.ts"] = files["src/server.ts"].replace(
            "body: artifact.data,",
            "body: artifact.data as unknown as BodyInit,",
        )
        files["src/server.ts"] = files["src/server.ts"].replace(
            'import { join } from "node:path";',
            'import { basename, join } from "node:path";',
        ).replace(
            'join(directory, part.filename || "submission.bin")',
            'join(directory, basename(part.filename || "submission.bin") || "submission.bin")',
        )
        files["src/server.ts"] = files["src/server.ts"].replace(
            'import { basename, join } from "node:path";',
            'import { basename, join } from "node:path";\nimport rawBody from "fastify-raw-body";',
        )
        files["src/server.ts"] = files["src/server.ts"].replace(
            "await app.register(multipart);",
            "await app.register(multipart);\\nawait app.register(rawBody, { field: \"rawBody\", global: false, routes: [\"/api/judge/callback\"], encoding: false, runFirst: true });",
        ).replace(
            "const raw = JSON.stringify(request.body);",
            "const raw = Buffer.isBuffer((request as any).rawBody) ? (request as any).rawBody.toString(\"utf8\") : JSON.stringify(request.body);",
        )
        files["src/server.ts"] = files["src/server.ts"].replace(
            "const data = Buffer.from(await tar.c({ cwd: directory, gzip: true, portable: true, mtime: new Date(0) }, [\".\"]));",
            "const stream = tar.c({ cwd: directory, gzip: true, portable: true, mtime: new Date(0) }, [\".\"]);\\n  const chunks: Buffer[] = [];\\n  for await (const chunk of stream) chunks.push(Buffer.from(chunk as Uint8Array));\\n  const data = Buffer.concat(chunks);",
        )
        files["src/server.ts"] = files["src/server.ts"].replace("\\n", "\n")
        return files
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
