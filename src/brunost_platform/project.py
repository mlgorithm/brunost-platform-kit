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
from brunost_platform.models import Contest, Submission, User, WorkerOperation
from brunost_platform.postgres import PostgresPlatformStore
from brunost_platform.store import SQLitePlatformStore


app = FastAPI(title="Brunost Competition Platform")
database = os.environ.get("BRUNOST_PLATFORM_DATABASE", "platform.db")
store = PostgresPlatformStore(database) if database.startswith(("postgres://", "postgresql://")) else SQLitePlatformStore(database)
judge = gateway_from_environment()
platform = PlatformApplication(judge, store=store)
identity = LocalIdentityAdapter(store)
submission_root = Path(os.environ.get("BRUNOST_SUBMISSION_ROOT", "submissions")).expanduser().resolve()
callback_url = os.environ.get("BRUNOST_PLATFORM_CALLBACK_URL", "http://127.0.0.1:3000/api/judge/callback")
service_token = os.environ.get("BRUNOST_PLATFORM_SERVICE_TOKEN", "")
default_admin_email = os.environ.get("BRUNOST_DEFAULT_ADMIN_EMAIL", "admin@example.org").strip().lower()
default_admin_password = os.environ.get("BRUNOST_DEFAULT_ADMIN_PASSWORD", "change-me-now")
if not store.list_users():
    identity.register(
        email=default_admin_email,
        password=default_admin_password,
        display_name=os.environ.get("BRUNOST_DEFAULT_ADMIN_NAME", "Country operator"),
        roles=("admin",),
        metadata={"must_change_password": True, "bootstrap_account": True},
    )


class RegisterIn(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=10)
    display_name: str = Field(min_length=1, max_length=120)


class LoginIn(BaseModel):
    email: str
    password: str


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=10)


class ContestIn(BaseModel):
    contest_id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=200)
    task_refs: list[str] = Field(default_factory=list)
    status: str = "draft"
    leaderboard_visible: bool = False
    best_attempt: bool = True


def current_user(request: Request, authorization: str | None = Header(default=None)):
    token = authorization.removeprefix("Bearer ").strip() if authorization else ""
    user = store.get_session_user(token) if token else None
    if user is None and service_token and token == service_token:
        subject = request.headers.get("x-brunost-subject", "").strip()
        if not subject:
            raise HTTPException(status_code=401, detail="external subject is required")
        roles = tuple(role.strip() for role in request.headers.get("x-brunost-roles", "").split(",") if role.strip())
        user = User(
            user_id=subject,
            email=request.headers.get("x-brunost-email", f"{subject}@external.invalid"),
            display_name=request.headers.get("x-brunost-display-name", subject),
            organization_id=request.headers.get("x-brunost-organization") or None,
            roles=roles,
            metadata={"external_identity": True},
        )
    if user is None:
        raise HTTPException(status_code=401, detail="login required")
    return user


def staff_user(user=Depends(current_user)):
    if not platform.policy.can_manage_platform(user):
        raise HTTPException(status_code=403, detail="organizer privileges required")
    return user


@app.get("/healthz")
def health():
    try:
        return {"status": "ok", "judge": judge.health()}
    except Exception as exc:  # noqa: BLE001 - expose dependency health to probes
        raise HTTPException(status_code=503, detail=f"Judge unavailable: {exc}") from exc


@app.post("/api/auth/register", status_code=201)
def register(request: RegisterIn):
    if store.get_user_by_email(request.email):
        raise HTTPException(status_code=409, detail="email is already registered")
    # The first account is the local administrator so a fresh standalone
    # deployment can create its first contest without editing the database.
    roles = ("admin",) if not store.list_users() else (("student",) if platform.policy.edition == "standalone" else ("contestant",))
    return identity.register(email=request.email, password=request.password, display_name=request.display_name, roles=roles).as_dict()


@app.post("/api/auth/login")
def login(request: LoginIn):
    token = identity.authenticate(email=request.email, password=request.password)
    if not token:
        raise HTTPException(status_code=401, detail="invalid credentials")
    return {"access_token": token, "token_type": "bearer"}


@app.post("/api/auth/change-password")
def change_password(request: ChangePasswordIn, user=Depends(current_user)):
    try:
        updated = identity.change_password(user_id=user.user_id, current_password=request.current_password, new_password=request.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return updated.as_dict()


@app.get("/api/me")
def me(user=Depends(current_user)):
    return user.as_dict()


@app.post("/api/contests", status_code=201)
def create_contest(request: ContestIn, user=Depends(staff_user)):
    return platform.create_contest(Contest(request.contest_id, request.name, tuple(request.task_refs), request.status, {"leaderboard_visible": request.leaderboard_visible, "best_attempt": request.best_attempt}), actor=user).as_dict()


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
    return """<!doctype html>
    <html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Brunost Platform</title>
    <style>
      :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
      body { margin: 0; min-height: 100vh; background: #0b1020; color: #eef2ff; }
      main { max-width: 920px; margin: 0 auto; padding: 12vh 28px; }
      .eyebrow { color: #a5b4fc; font-size: .78rem; font-weight: 700; letter-spacing: .14em; text-transform: uppercase; }
      h1 { margin: 14px 0; font-size: clamp(2.6rem, 7vw, 5.5rem); letter-spacing: -.06em; line-height: .95; }
      p { max-width: 650px; color: #a9b5d6; font-size: 1.08rem; line-height: 1.7; }
      nav { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 32px; }
      a { display: inline-flex; align-items: center; border-radius: 12px; padding: 12px 16px; background: #6366f1; color: white; font-weight: 700; text-decoration: none; }
      a.secondary { background: #17213c; color: #dbe4ff; }
    </style></head><body><main>
      <div class="eyebrow">Brunost competition platform</div>
      <h1>Run better contests.</h1>
      <p>Manage people, contests, tasks, submissions, workers, evaluations, and leaderboards from one platform. The Judge remains an independent execution service behind the control room.</p>
      <nav><a href="/admin">Open admin control room</a><a class="secondary" href="/contests">Browse contests</a><a class="secondary" href="/login">Sign in</a></nav>
    </main></body></html>"""


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


def _admin_ui_appendix() -> str:
    """Return the operator dashboard added to generated FastAPI projects."""
    return r'''


# ---------------------------------------------------------------------------
# Operator UI
# ---------------------------------------------------------------------------
# The dashboard is intentionally generated into the application so a country
# can start with one command and later replace these pages with React, Vue, or
# its own server-rendered frontend. The Judge remains the source of truth for
# execution, workers, tasks, and evaluation state.
import html
from datetime import UTC, datetime
from urllib.parse import quote

from fastapi.responses import RedirectResponse


ADMIN_CSS = """
:root { --ink:#172033; --muted:#6b7890; --line:#e5eaf2; --surface:#fff; --wash:#f5f7fb; --brand:#5b5ce2; --brand-dark:#4547bd; --good:#16845b; --warn:#b86b00; --bad:#c43d52; }
* { box-sizing:border-box; }
body { margin:0; color:var(--ink); background:var(--wash); font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
a { color:inherit; text-decoration:none; }
.shell { display:flex; min-height:100vh; }
.sidebar { width:252px; padding:28px 18px; color:#dce3ff; background:#171a31; position:fixed; inset:0 auto 0 0; }
.brand { display:flex; align-items:center; gap:11px; margin:0 10px 36px; font-weight:800; letter-spacing:-.03em; color:#fff; font-size:20px; }
.brand-mark { display:grid; place-items:center; width:34px; height:34px; border-radius:11px; color:#fff; background:linear-gradient(135deg,#7e80ff,#4d50d4); }
.nav-label { margin:24px 11px 8px; color:#7e88aa; text-transform:uppercase; font-size:10px; font-weight:800; letter-spacing:.14em; }
.nav a { display:flex; gap:12px; align-items:center; padding:11px 12px; border-radius:10px; color:#aeb8d8; font-size:14px; }
.nav a:hover,.nav a.active { color:#fff; background:#292e50; }
.sidebar-foot { position:absolute; right:18px; bottom:24px; left:18px; padding:13px; border:1px solid #303758; border-radius:12px; color:#9ca8ca; font-size:12px; }
.main { width:calc(100% - 252px); margin-left:252px; padding:34px 42px 60px; }
.topbar { display:flex; justify-content:space-between; gap:20px; align-items:center; margin-bottom:30px; }
.topbar h1 { margin:0; font-size:30px; letter-spacing:-.045em; }
.topbar p { margin:6px 0 0; color:var(--muted); font-size:14px; }
.user-chip { display:flex; align-items:center; gap:10px; padding:8px 12px 8px 8px; border:1px solid var(--line); border-radius:999px; background:var(--surface); font-size:13px; }
.avatar { display:grid; place-items:center; width:30px; height:30px; border-radius:50%; color:#fff; background:var(--brand); font-weight:800; }
.grid { display:grid; gap:18px; }
.grid.four { grid-template-columns:repeat(4,minmax(0,1fr)); }
.grid.two { grid-template-columns:repeat(2,minmax(0,1fr)); }
.card { padding:22px; border:1px solid var(--line); border-radius:16px; background:var(--surface); box-shadow:0 5px 20px rgba(31,43,76,.035); }
.metric-label { color:var(--muted); font-size:12px; font-weight:700; }
.metric { margin-top:8px; font-size:30px; font-weight:800; letter-spacing:-.05em; }
.metric-note { margin-top:6px; color:var(--muted); font-size:12px; }
.section { margin-top:22px; }
.section-head,.page-head { display:flex; align-items:flex-end; justify-content:space-between; gap:20px; margin-bottom:14px; }
.section-head h2,.page-head h2 { margin:0; font-size:18px; letter-spacing:-.025em; }
.section-head p,.page-head p { margin:5px 0 0; color:var(--muted); font-size:13px; }
.eyebrow { margin:0 0 7px !important; color:var(--brand) !important; font-size:11px !important; text-transform:uppercase; letter-spacing:.14em; font-weight:800; }
.button { display:inline-flex; align-items:center; justify-content:center; gap:7px; padding:10px 14px; border:0; border-radius:9px; color:#fff; background:var(--brand); cursor:pointer; font:inherit; font-size:13px; font-weight:750; }
.button:hover { background:var(--brand-dark); }
.button.secondary { color:var(--ink); background:#edf0f7; }
.button.danger { background:#fff0f2; color:var(--bad); }
.button.small { padding:7px 10px; font-size:12px; }
.worker-actions { display:flex; flex-wrap:wrap; gap:8px; align-items:center; min-width:270px; }
.worker-actions form { display:flex; flex-wrap:wrap; gap:6px; align-items:center; }
.worker-actions input { width:160px; padding:7px 9px; font-size:12px; }
.danger-zone { margin-top:8px; padding-top:8px; border-top:1px solid #f0d9de; }
.danger-zone summary { color:var(--bad); cursor:pointer; font-size:12px; font-weight:750; }
.danger-zone form { display:grid; gap:7px; margin-top:8px; }
.danger-zone input { width:100%; }
.operation-error { color:var(--bad); font-size:12px; }
.table-wrap { overflow:auto; border:1px solid var(--line); border-radius:13px; background:var(--surface); }
table { width:100%; border-collapse:collapse; font-size:13px; }
th { padding:12px 16px; color:var(--muted); background:#fafbfe; text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:.08em; }
td { padding:14px 16px; border-top:1px solid var(--line); vertical-align:middle; }
tr:hover td { background:#fcfcff; }
.pill { display:inline-flex; align-items:center; gap:5px; padding:4px 8px; border-radius:999px; color:var(--muted); background:#eef1f6; font-size:11px; font-weight:750; }
.pill.good { color:var(--good); background:#eaf8f1; }
.pill.warn { color:var(--warn); background:#fff4df; }
.pill.bad { color:var(--bad); background:#ffedf0; }
.mono { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px; }
.empty { padding:32px; color:var(--muted); text-align:center; }
.form-card { max-width:800px; }
form.stack { display:grid; gap:14px; }
.form-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; }
label { display:grid; gap:6px; color:var(--muted); font-size:12px; font-weight:700; }
input,select,textarea { width:100%; padding:11px 12px; border:1px solid #dce2ed; border-radius:9px; outline:none; color:var(--ink); background:#fff; font:inherit; font-size:13px; }
input:focus,select:focus,textarea:focus { border-color:var(--brand); box-shadow:0 0 0 3px #e9e9ff; }
.hint { color:var(--muted); font-size:12px; line-height:1.55; }
.notice { padding:12px 14px; border-radius:10px; color:#31506d; background:#edf7ff; font-size:13px; }
.notice.error { color:#8e2939; background:#ffedf0; }
.health-dot { display:inline-block; width:8px; height:8px; margin-right:6px; border-radius:50%; background:var(--good); }
@media (max-width:1000px) { .grid.four { grid-template-columns:repeat(2,minmax(0,1fr)); } .sidebar { width:210px; } .main { width:calc(100% - 210px); margin-left:210px; padding:26px; } }
@media (max-width:700px) { .sidebar { position:static; width:100%; min-height:auto; } .sidebar-foot { position:static; margin-top:20px; } .shell { display:block; } .main { width:100%; margin:0; padding:22px 16px 40px; } .grid.four,.grid.two,.form-grid { grid-template-columns:1fr; } .topbar,.section-head,.page-head { align-items:flex-start; flex-direction:column; } }
"""


def _admin_escape(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _admin_page(title: str, content: str, *, user=None, active: str = "dashboard") -> str:
    links = [("dashboard", "◈", "Overview", "/admin"), ("contests", "◇", "Contests", "/admin/contests"), ("evaluations", "◌", "Evaluations", "/admin/evaluations"), ("workers", "♢", "Workers", "/admin/workers"), ("definitions", "⌘", "Agents & games", "/admin/definitions")]
    if platform.policy.global_task_library_enabled:
        links.insert(1, ("tasks", "▣", "Tasks", "/admin/tasks"))
    nav = "".join(f'<a class="{("active" if key == active else "")}" href="{href}"><span>{icon}</span>{label}</a>' for key, icon, label, href in links)
    name = _admin_escape(getattr(user, "display_name", "Operator"))
    initial = _admin_escape((getattr(user, "display_name", "O") or "O")[:1].upper())
    return "<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>" + _admin_escape(title) + " · Brunost" + "</title><style>" + ADMIN_CSS + "</style></head><body><div class='shell'><aside class='sidebar'><a class='brand' href='/admin'><span class='brand-mark'>B</span>Brunost <span style='font-weight:500;color:#8490b4'>control</span></a><div class='nav-label'>Operations</div><nav class='nav'>" + nav + "</nav><div class='sidebar-foot'>Judge-backed platform<br><span style='color:#6ed6a7'>●</span> control plane connected through API</div></aside><main class='main'><div class='topbar'><div><h1>" + _admin_escape(title) + "</h1><p>Competition operations, task authoring, and evaluation control.</p></div><div class='user-chip'><span class='avatar'>" + initial + "</span><span>" + name + "</span><a class='button secondary small' href='/logout'>Sign out</a></div></div>" + content + "</main></div></body></html>"


def _admin_user_or_redirect(request: Request):
    user = _browser_session_user(request)
    if user is None:
        return None, RedirectResponse("/login?next=" + quote(request.url.path), status_code=303)
    if user.metadata.get("must_change_password"):
        return None, RedirectResponse("/change-password?next=" + quote(request.url.path), status_code=303)
    if not platform.policy.can_manage_platform(user):
        return None, HTMLResponse(_admin_page("Access denied", "<div class='card notice error'>Organizer privileges are required for this area.</div>"), status_code=403)
    return user, None


def _browser_session_user(request: Request):
    token = request.cookies.get("brunost_session") or request.query_params.get("token")
    return store.get_session_user(token) if token else None


def _admin_judge_snapshot() -> dict:
    snapshot = {}
    for key, method, default in (("health", "health", {}), ("stats", "stats", {}), ("tasks", "list_tasks", []), ("workers", "list_workers", []), ("executions", "list_executions", []), ("agents", "list_agents", []), ("games", "list_games", [])):
        try:
            snapshot[key] = getattr(judge, method)()
        except Exception as exc:  # noqa: BLE001 - dashboard should show degraded dependencies
            snapshot[key] = default
            snapshot.setdefault("errors", []).append(f"{key}: {exc}")
    return snapshot


def _admin_stat(label: str, value, note: str) -> str:
    return "<div class='card'><div class='metric-label'>" + _admin_escape(label) + "</div><div class='metric'>" + _admin_escape(value) + "</div><div class='metric-note'>" + _admin_escape(note) + "</div></div>"


def _admin_status(value: str) -> str:
    normalized = str(value).lower()
    kind = "good" if normalized in {"ok", "ready", "running", "completed", "healthy", "succeeded", "paused", "resumed", "revoked"} else "warn" if normalized in {"queued", "busy", "pending", "draining"} else "bad" if normalized in {"failed", "error", "offline", "cancelled"} else ""
    return f"<span class='pill {kind}'>{_admin_escape(value)}</span>"


def _worker_action_form(worker_id: str, action: str, label: str, *, danger: bool = False) -> str:
    encoded_worker_id = quote(str(worker_id), safe="")
    button_class = "button danger small" if danger else "button secondary small"
    return "<form method='post' action='/admin/workers/" + encoded_worker_id + "/action'><input type='hidden' name='action' value='" + _admin_escape(action) + "'><input name='reason' required maxlength='500' placeholder='Reason for change' aria-label='Reason for change'><button class='" + button_class + "' type='submit'>" + _admin_escape(label) + "</button></form>"


def _worker_actions(worker: dict) -> str:
    worker_id = str(worker.get("worker_id") or "")
    toggle = _worker_action_form(worker_id, "resume", "Resume") if worker.get("draining") else _worker_action_form(worker_id, "pause", "Pause")
    encoded_worker_id = quote(worker_id, safe="")
    revoke = "<details class='danger-zone'><summary>Revoke credential</summary><form method='post' action='/admin/workers/" + encoded_worker_id + "/action'><input type='hidden' name='action' value='revoke'><input name='reason' required maxlength='500' placeholder='Why is this credential being revoked?' aria-label='Revocation reason'><input name='confirm_text' required pattern='REVOKE' placeholder='Type REVOKE to confirm' aria-label='Type REVOKE to confirm'><button class='button danger small' type='submit'>Revoke access</button></form></details>"
    return "<div class='worker-actions'>" + toggle + revoke + "</div>"


def _admin_slugify(value: str) -> str:
    normalized = "".join(character.lower() if character.isalnum() else "-" for character in value.strip())
    return "-".join(part for part in normalized.split("-") if part)[:80]


def _admin_judge_kind(task_type: str) -> str:
    return {"code_training": "ioi", "training_code": "model", "model_prediction": "model", "multiple_choice": "icpc", "agent_arena": "game", "agent_environment": "agent"}.get(task_type, "ioi")


def _admin_scaffold_task_package(contest_id: str, slug: str, task_type: str) -> str:
    root = Path(os.environ.get("BRUNOST_TASK_ROOT", "tasks")).expanduser().resolve() / _admin_slugify(contest_id) / slug
    (root / "scorer").mkdir(parents=True, exist_ok=True)
    (root / "public").mkdir(parents=True, exist_ok=True)
    (root / "private").mkdir(parents=True, exist_ok=True)
    (root / "tests").mkdir(parents=True, exist_ok=True)
    kind = _admin_judge_kind(task_type)
    (root / "judge.yaml").write_text(f"version: 1\nkind: {kind}\nruntime: python-3.13\nscoring: scorer.metrics:evaluate\nnetwork: disabled\n", encoding="utf-8")
    (root / "scorer" / "metrics.py").write_text("def evaluate(submission_path: str, assets_path: str) -> dict[str, float]:\n    _ = submission_path, assets_path\n    return {'public': 0.0}\n", encoding="utf-8")
    (root / "public" / "README.md").write_text("Put contestant-visible files here.\n", encoding="utf-8")
    (root / "private" / ".gitkeep").write_text("", encoding="utf-8")
    (root / "tests" / "test_task.py").write_text("# Add deterministic scorer tests here.\n", encoding="utf-8")
    return str(root)


def _admin_register_task(contest_id: str, *, title: str, slug: str, task_type: str, template_key: str = "", time_limit: str = "900", points: str = "", artifact_id: str = "", path: str = "") -> str:
    clean_title = title.strip()
    clean_slug = _admin_slugify(slug or title)
    if not clean_title or not clean_slug:
        raise ValueError("each task needs a title and slug")
    try:
        limit = int(time_limit or "900")
    except ValueError as exc:
        raise ValueError(f"task '{clean_title}' has an invalid time limit") from exc
    if limit <= 0:
        raise ValueError(f"task '{clean_title}' needs a positive time limit")
    score_points = None
    if points.strip():
        try:
            score_points = int(points)
        except ValueError as exc:
            raise ValueError(f"task '{clean_title}' has invalid points") from exc
        if score_points < 0:
            raise ValueError(f"task '{clean_title}' needs non-negative points")
    if artifact_id and path:
        raise ValueError(f"task '{clean_title}' needs exactly one artifact ID or local path")
    task_ref = f"{_admin_slugify(contest_id)}/{clean_slug}"
    if not artifact_id and not path:
        path = _admin_scaffold_task_package(contest_id, clean_slug, task_type)
        uploaded = judge.upload_artifact(path)
        artifact_id = str(uploaded.get("artifact_id") or "")
        if not artifact_id:
            raise ValueError(f"Judge did not return an artifact ID for '{clean_title}'")
    metadata = {"title": clean_title, "slug": clean_slug, "task_type": task_type, "template_key": template_key, "time_limit_seconds": limit, "points": score_points, "contest_id": contest_id}
    payload = {"task_ref": task_ref, "kind": _admin_judge_kind(task_type), "metadata": metadata, "runtime": "python-3.13"}
    payload["artifact_id" if artifact_id else "path"] = artifact_id or path
    judge.register_task(**payload)
    return task_ref


@app.get("/login", response_class=HTMLResponse)
def browser_login(next: str = "/admin"):
    content = "<div class='card form-card'><div class='page-head'><div><p class='eyebrow'>Operator access</p><h2>Sign in to Brunost</h2><p>Use the bootstrap account from <span class='mono'>BRUNOST_DEFAULT_ADMIN_EMAIL</span> and <span class='mono'>BRUNOST_DEFAULT_ADMIN_PASSWORD</span>.</p></div></div><form class='stack' method='post' action='/login'><input type='hidden' name='next' value='" + _admin_escape(next) + "'><label>Email<input type='email' name='email' required autocomplete='email'></label><label>Password<input type='password' name='password' required autocomplete='current-password'></label><button class='button' type='submit'>Continue to dashboard</button></form><p class='hint'>The bootstrap password is temporary. You must replace it before using the control room.</p></div>"
    return _admin_page("Sign in", content)


@app.post("/login", response_class=HTMLResponse)
def browser_login_submit(email: str = Form(...), password: str = Form(...), next: str = Form("/admin")):
    token = identity.authenticate(email=email, password=password)
    if not token:
        content = "<div class='card form-card'><div class='notice error'>Invalid email or password.</div><p><a class='button secondary' href='/login'>Try again</a></p></div>"
        return HTMLResponse(_admin_page("Sign in", content), status_code=401)
    user = store.get_session_user(token)
    destination = next if next.startswith("/") else "/admin"
    if user and user.metadata.get("must_change_password"):
        destination = "/change-password?next=" + quote(destination)
    response = RedirectResponse(destination, status_code=303)
    response.set_cookie("brunost_session", token, httponly=True, samesite="lax", max_age=86400)
    return response


@app.get("/change-password", response_class=HTMLResponse)
def browser_change_password(request: Request, next: str = "/admin"):
    user = _browser_session_user(request)
    if user is None:
        return RedirectResponse("/login?next=" + quote("/change-password"), status_code=303)
    content = "<div class='card form-card'><div class='page-head'><div><p class='eyebrow'>First-run security</p><h2>Change your password</h2><p>The temporary bootstrap password must be replaced before continuing.</p></div></div><form class='stack' method='post' action='/change-password'><input type='hidden' name='next' value='" + _admin_escape(next) + "'><label>Current password<input type='password' name='current_password' required autocomplete='current-password'></label><label>New password<input type='password' name='new_password' minlength='10' required autocomplete='new-password'></label><label>Confirm new password<input type='password' name='confirm_password' minlength='10' required autocomplete='new-password'></label><button class='button' type='submit'>Save new password</button></form><p class='hint'>Use at least 10 characters. Store the new password in your country operator password manager.</p></div>"
    return _admin_page("Change password", content, user=user)


@app.post("/change-password", response_class=HTMLResponse)
def browser_change_password_submit(request: Request, current_password: str = Form(...), new_password: str = Form(...), confirm_password: str = Form(...), next: str = Form("/admin")):
    user = _browser_session_user(request)
    if user is None:
        return RedirectResponse("/login?next=" + quote("/change-password"), status_code=303)
    if new_password != confirm_password:
        detail = "The new password and confirmation do not match."
    else:
        try:
            identity.change_password(user_id=user.user_id, current_password=current_password, new_password=new_password)
            destination = next if next.startswith("/") else "/admin"
            return RedirectResponse(destination, status_code=303)
        except ValueError as exc:
            detail = str(exc)
    content = "<div class='card form-card'><div class='notice error'>" + _admin_escape(detail) + "</div><p><a class='button secondary' href='/change-password'>Try again</a></p></div>"
    return HTMLResponse(_admin_page("Change password", content, user=user), status_code=422)


@app.get("/logout")
def browser_logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("brunost_session")
    return response


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    user, response = _admin_user_or_redirect(request)
    if response:
        return response
    data = _admin_judge_snapshot()
    stats = data.get("stats") or {}
    workers = data.get("workers") or []
    executions = data.get("executions") or []
    contests = store.list_contests()
    users = store.list_users()
    ready = sum(1 for worker in workers if worker.get("status") in {"ready", "busy"} and not worker.get("draining"))
    active = sum(1 for item in executions if item.get("status") in {"queued", "running"})
    health = data.get("health") or {}
    cards = "<div class='grid four'>" + _admin_stat("Judge status", "Online" if health.get("status") == "ok" else "Degraded", "control plane") + _admin_stat("Tasks", len(data.get("tasks") or []), "registered task packages") + _admin_stat("Workers", f"{ready}/{len(workers)}", "ready workers") + _admin_stat("Active evaluations", active, "queued or running") + "</div>"
    worker_rows = "".join("<tr><td><strong>" + _admin_escape(item.get("worker_id")) + "</strong></td><td>" + _admin_status("draining" if item.get("draining") else item.get("status", "unknown")) + "</td><td>" + _admin_escape(", ".join(item.get("resource_classes") or [])) + "</td><td>" + _admin_escape(item.get("region") or "—") + "</td></tr>" for item in workers[:8]) or "<tr><td colspan='4' class='empty'>No workers enrolled yet.</td></tr>"
    evaluation_rows = "".join("<tr><td class='mono'>" + _admin_escape(str(item.get("execution_id", ""))[:12]) + "</td><td>" + _admin_escape(item.get("task_ref")) + "</td><td>" + _admin_status(item.get("status", "unknown")) + "</td><td>" + _admin_escape(item.get("score") if item.get("score") is not None else "—") + "</td></tr>" for item in executions[:8]) or "<tr><td colspan='4' class='empty'>No evaluations yet.</td></tr>"
    content = cards + "<div class='grid two section'><section><div class='section-head'><div><h2>Worker fleet</h2><p>Live capacity reported by the Judge.</p></div><a class='button secondary small' href='/admin/workers'>View all</a></div><div class='table-wrap'><table><thead><tr><th>Worker</th><th>Status</th><th>Resources</th><th>Region</th></tr></thead><tbody>" + worker_rows + "</tbody></table></div></section><section><div class='section-head'><div><h2>Recent evaluations</h2><p>Execution state from the Judge.</p></div><a class='button secondary small' href='/admin/evaluations'>View all</a></div><div class='table-wrap'><table><thead><tr><th>ID</th><th>Task</th><th>Status</th><th>Score</th></tr></thead><tbody>" + evaluation_rows + "</tbody></table></div></section></div>"
    task_action = "<a class='button' href='/admin/tasks/new'>Register a task</a> " if platform.policy.global_task_library_enabled else ""
    content += "<div class='grid two section'><section class='card'><div class='section-head'><div><h2>Platform</h2><p>Owned by this application.</p></div></div><div class='grid two'><div><div class='metric-label'>Users</div><div class='metric'>" + str(len(users)) + "</div></div><div><div class='metric-label'>Contests</div><div class='metric'>" + str(len(contests)) + "</div></div></div></section><section class='card'><div class='section-head'><div><h2>Quick actions</h2><p>Common operator workflows.</p></div></div><p>" + task_action + "<a class='button secondary' href='/admin/contests/new'>Create a contest</a></p><p class='hint'>Task packages and execution state remain Judge-owned; contests and leaderboard policy remain Platform-owned.</p></section></div>"
    return _admin_page("Operations overview", content, user=user, active="dashboard")


@app.get("/admin/tasks", response_class=HTMLResponse)
def admin_tasks(request: Request):
    user, response = _admin_user_or_redirect(request)
    if response:
        return response
    if not platform.policy.global_task_library_enabled:
        return HTMLResponse(_admin_page("Not available", "<div class='card notice'>The standalone profile creates problems inside a contest. Enable the global task-library capability for an advanced deployment.</div><p><a class='button secondary' href='/admin/contests'>Open contests</a></p>", user=user), status_code=404)
    tasks = _admin_judge_snapshot().get("tasks") or []
    rows = "".join("<tr><td><strong>" + _admin_escape((item.get("manifest") or {}).get("title") or item.get("task_ref")) + "</strong><div class='hint mono'>" + _admin_escape(item.get("task_ref")) + "</div></td><td>" + _admin_status((item.get("manifest") or {}).get("task_type") or item.get("kind", "unknown")) + "</td><td>" + _admin_escape((item.get("manifest") or {}).get("points") if (item.get("manifest") or {}).get("points") is not None else "—") + "</td><td>" + _admin_escape((item.get("manifest") or {}).get("time_limit_seconds", "—")) + " sec</td><td class='mono'>" + _admin_escape(str((item.get("manifest") or {}).get("digest", "—"))[:16]) + "</td></tr>" for item in tasks) or "<tr><td colspan='5' class='empty'>No task packages registered.</td></tr>"
    content = "<div class='page-head'><div><p class='eyebrow'>Judge registry</p><h2>Task packages</h2><p>Register immutable IOI, ICPC, IOAI, agent, and game task definitions.</p></div><a class='button' href='/admin/tasks/new'>Register task</a></div><div class='table-wrap'><table><thead><tr><th>Problem</th><th>Type</th><th>Points</th><th>Time limit</th><th>Digest</th></tr></thead><tbody>" + rows + "</tbody></table></div>"
    return _admin_page("Tasks", content, user=user, active="tasks")


@app.get("/admin/tasks/new", response_class=HTMLResponse)
def admin_task_form(request: Request):
    user, response = _admin_user_or_redirect(request)
    if response:
        return response
    if not platform.policy.global_task_library_enabled:
        return HTMLResponse(_admin_page("Not available", "<div class='card notice'>The standalone profile creates problems inside a contest. Enable the global task-library capability for an advanced deployment.</div>", user=user), status_code=404)
    kinds = "".join(f"<option value='{kind}'>{kind.upper()}</option>" for kind in ("ioai", "ioi", "icpc", "interactive", "model", "agent", "game", "output-only"))
    content = "<div class='page-head'><div><p class='eyebrow'>Judge registry</p><h2>Register a task</h2><p>Use an artifact ID for a distributed deployment, or a local path for development.</p></div></div><div class='card form-card'><form class='stack' method='post' action='/admin/tasks'><div class='form-grid'><label>Task reference<input name='task_ref' placeholder='national-2026/forecast-v1' required></label><label>Task kind<select name='kind'>" + kinds + "</select></label></div><label>Immutable artifact ID<input name='artifact_id' placeholder='64-character content hash'></label><label>Local task path<input name='path' placeholder='/srv/tasks/forecast-v1'></label><div class='notice'>Provide exactly one of artifact ID or local path. Artifact IDs are the portable production option.</div><button class='button' type='submit'>Register task with Judge</button></form></div>"
    return _admin_page("Register task", content, user=user, active="tasks")


@app.post("/admin/tasks", response_class=HTMLResponse)
def admin_task_create(request: Request, task_ref: str = Form(...), kind: str = Form("ioai"), artifact_id: str = Form(""), path: str = Form("")):
    user, response = _admin_user_or_redirect(request)
    if response:
        return response
    if not platform.policy.global_task_library_enabled:
        return HTMLResponse(_admin_page("Not available", "<div class='card notice'>The standalone profile creates problems inside a contest. Enable the global task-library capability for an advanced deployment.</div>", user=user), status_code=404)
    if bool(artifact_id.strip()) == bool(path.strip()):
        content = "<div class='card notice error'>Provide exactly one artifact ID or local task path.</div><p><a class='button secondary' href='/admin/tasks/new'>Go back</a></p>"
        return HTMLResponse(_admin_page("Register task", content, user=user, active="tasks"), status_code=422)
    payload = {"task_ref": task_ref.strip(), "kind": kind.strip()}
    payload["artifact_id" if artifact_id.strip() else "path"] = (artifact_id if artifact_id.strip() else path).strip()
    try:
        judge.register_task(**payload)
    except Exception as exc:  # noqa: BLE001 - show Judge validation in the operator UI
        content = "<div class='card notice error'>Task registration failed: " + _admin_escape(exc) + "</div><p><a class='button secondary' href='/admin/tasks/new'>Try again</a></p>"
        return HTMLResponse(_admin_page("Register task", content, user=user, active="tasks"), status_code=400)
    return RedirectResponse("/admin/tasks", status_code=303)


@app.get("/admin/contests", response_class=HTMLResponse)
def admin_contests(request: Request):
    user, response = _admin_user_or_redirect(request)
    if response:
        return response
    contests = store.list_contests()
    rows = "".join("<tr><td><a class='text-brand' href='/admin/contests/" + quote(contest.contest_id) + "'><strong>" + _admin_escape(contest.contest_id) + "</strong></a></td><td>" + _admin_escape(contest.name) + "</td><td>" + _admin_escape(len(contest.task_refs)) + " tasks</td><td>" + _admin_status(contest.status) + "</td><td>" + ("Public" if contest.metadata.get("leaderboard_visible") else "Hidden") + "</td></tr>" for contest in contests) or "<tr><td colspan='5' class='empty'>No contests created.</td></tr>"
    content = "<div class='page-head'><div><p class='eyebrow'>Platform registry</p><h2>Contests</h2><p>Define contest identity, task selection, and leaderboard visibility.</p></div><a class='button' href='/admin/contests/new'>Create contest</a></div><div class='table-wrap'><table><thead><tr><th>ID</th><th>Name</th><th>Tasks</th><th>Status</th><th>Leaderboard</th></tr></thead><tbody>" + rows + "</tbody></table></div>"
    return _admin_page("Contests", content, user=user, active="contests")


@app.get("/admin/contests/new", response_class=HTMLResponse)
def admin_contest_form(request: Request):
    user, response = _admin_user_or_redirect(request)
    if response:
        return response
    tasks = _admin_judge_snapshot().get("tasks") or []
    existing = "".join("<label style='display:flex;grid-template-columns:auto 1fr;align-items:start;gap:9px;padding:9px 0;font-weight:600'><input type='checkbox' name='selected_task_ref' value='" + _admin_escape(item.get("task_ref")) + "' style='width:auto;margin-top:2px'><span>" + _admin_escape(item.get("task_ref")) + "<small class='hint' style='display:block;font-weight:400'>" + _admin_escape(item.get("kind", "task")) + " · " + _admin_escape((item.get("manifest") or {}).get("runtime", "runtime unspecified")) + "</small></span></label>" for item in tasks)
    existing = existing or "<div class='empty' style='padding:12px 0;text-align:left'>No registered Judge tasks yet. Add the first task below.</div>"
    task_row = "<div class='task-row card' style='display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:10px;padding:14px;background:#fafbfe'><label>Problem title<input name='new_task_title' placeholder='Maximum subarray'></label><label>Slug<input name='new_task_slug' placeholder='maximum-subarray'></label><label style='grid-column:1/-1'>Task type<select name='new_task_type'><option value='code_training'>Code (judged)</option><option value='training_code'>AI training code</option><option value='model_prediction'>Model / prediction</option><option value='multiple_choice'>Quiz</option><option value='agent_arena'>Agent arena</option><option value='agent_environment'>Agent environment</option></select></label><label>Competition preset<select name='new_task_template'><option value=''>No preset</option><option value='ioi'>IOI / subtasks</option><option value='icpc'>ICPC / batch judging</option><option value='ioai-model'>IOAI / model prediction</option><option value='quiz'>Quiz / multiple choice</option></select></label><label>Time limit (seconds)<input name='new_task_time_limit' type='number' min='1' value='900'></label><label>Points<input name='new_task_points' type='number' min='0' placeholder='100'></label><label>Artifact ID (optional)<input name='new_task_artifact_id' placeholder='Auto-scaffold if empty'></label><label>Local package path (optional)<input name='new_task_path' placeholder='Used for development'></label></div>"
    content = "<div class='page-head'><div><p class='eyebrow'>Platform registry</p><h2>Create a contest</h2><p>Create the contest first, then define problems with the same title, slug, type, preset, time limit, and points workflow used by Brunost.</p></div></div><div class='card form-card'><form class='stack' method='post' action='/admin/contests'><div class='form-grid'><label>Contest ID<input name='contest_id' placeholder='national-final-2026' required></label><label>Display name<input name='name' placeholder='National Final 2026' required></label></div><div><label>Registered Judge tasks</label><div class='card' style='margin-top:8px;padding:12px;background:#fafbfe'>" + existing + "</div><p class='hint'>Select tasks already registered with the Judge, or create new Brunost-style problems below.</p></div><div><label>Additional task references<textarea name='task_refs' rows='2' placeholder='Optional: one existing task_ref per line or comma-separated'></textarea></label></div><div><label>Problems to create</label><p class='hint'>Leave package fields empty to generate a starter Judge package automatically. Open the contest workspace afterward to add more problems and edit their task packages.</p><div id='new-task-rows'>" + task_row + "</div><button class='button secondary small' type='button' onclick='addTaskRow()' style='margin-top:10px'>+ Add another problem</button><script>function addTaskRow(){const first=document.querySelector('.task-row');const row=first.cloneNode(true);row.querySelectorAll('input').forEach(function(input){if(input.name !== 'new_task_time_limit') input.value=''});document.getElementById('new-task-rows').appendChild(row)}</script></div><div class='form-grid'><label><span>Leaderboard <select name='leaderboard_visible'><option value='hidden'>Hidden during contest</option><option value='visible'>Visible</option></select></span></label><label><span>Attempts <select name='best_attempt'><option value='best'>Best attempt per task</option><option value='all'>All attempts</option></select></span></label></div><button class='button' type='submit'>Create contest</button></form></div>"
    return _admin_page("Create contest", content, user=user, active="contests")


@app.post("/admin/contests", response_class=HTMLResponse)
def admin_contest_create(request: Request, contest_id: str = Form(...), name: str = Form(...), task_refs: str = Form(""), selected_task_ref: list[str] | None = Form(None), new_task_title: list[str] | None = Form(None), new_task_slug: list[str] | None = Form(None), new_task_type: list[str] | None = Form(None), new_task_template: list[str] | None = Form(None), new_task_time_limit: list[str] | None = Form(None), new_task_points: list[str] | None = Form(None), new_task_artifact_id: list[str] | None = Form(None), new_task_path: list[str] | None = Form(None), leaderboard_visible: str = Form("hidden"), best_attempt: str = Form("best")):
    user, response = _admin_user_or_redirect(request)
    if response:
        return response
    refs_list: list[str] = []
    for value in (selected_task_ref or []) + [item for item in task_refs.replace(",", "\n").splitlines() if item.strip()]:
        normalized = value.strip()
        if normalized and normalized not in refs_list:
            refs_list.append(normalized)
    for index, raw_title in enumerate(new_task_title or []):
        title = raw_title.strip()
        if not title:
            continue
        slug = (new_task_slug[index] if new_task_slug and index < len(new_task_slug) else "").strip()
        task_type = (new_task_type[index] if new_task_type and index < len(new_task_type) else "code_training").strip() or "code_training"
        template_key = (new_task_template[index] if new_task_template and index < len(new_task_template) else "").strip()
        time_limit = (new_task_time_limit[index] if new_task_time_limit and index < len(new_task_time_limit) else "900").strip() or "900"
        points = (new_task_points[index] if new_task_points and index < len(new_task_points) else "").strip()
        artifact_id = (new_task_artifact_id[index] if new_task_artifact_id and index < len(new_task_artifact_id) else "").strip()
        path = (new_task_path[index] if new_task_path and index < len(new_task_path) else "").strip()
        try:
            task_ref = _admin_register_task(contest_id, title=title, slug=slug, task_type=task_type, template_key=template_key, time_limit=time_limit, points=points, artifact_id=artifact_id, path=path)
        except Exception as exc:  # noqa: BLE001 - show Judge validation in the operator UI
            content = "<div class='card notice error'>Could not create problem '" + _admin_escape(title) + "': " + _admin_escape(exc) + "</div><p><a class='button secondary' href='/admin/contests/new'>Go back</a></p>"
            return HTMLResponse(_admin_page("Create contest", content, user=user, active="contests"), status_code=400)
        if task_ref not in refs_list:
            refs_list.append(task_ref)
    refs = tuple(refs_list)
    try:
        platform.create_contest(Contest(contest_id.strip(), name.strip(), refs, metadata={"leaderboard_visible": leaderboard_visible == "visible", "best_attempt": best_attempt == "best"}), actor=user)
    except Exception as exc:  # noqa: BLE001 - surface store validation in the UI
        content = "<div class='card notice error'>Contest creation failed: " + _admin_escape(exc) + "</div><p><a class='button secondary' href='/admin/contests/new'>Try again</a></p>"
        return HTMLResponse(_admin_page("Create contest", content, user=user, active="contests"), status_code=400)
    return RedirectResponse("/admin/contests/" + quote(contest_id.strip()), status_code=303)


@app.get("/admin/contests/{contest_id}", response_class=HTMLResponse)
def admin_contest_workspace(request: Request, contest_id: str):
    user, response = _admin_user_or_redirect(request)
    if response:
        return response
    contest = store.get_contest(contest_id)
    if contest is None:
        return HTMLResponse(_admin_page("Contest not found", "<div class='card notice error'>This contest does not exist.</div><p><a class='button secondary' href='/admin/contests'>Back to contests</a></p>", user=user, active="contests"), status_code=404)
    task_map = {item.get("task_ref"): item for item in (_admin_judge_snapshot().get("tasks") or [])}
    rows = "".join("<tr><td><strong>" + _admin_escape((task_map.get(ref) or {}).get("manifest", {}).get("title") or ref.rsplit("/", 1)[-1]) + "</strong><div class='hint mono'>" + _admin_escape(ref) + "</div></td><td>" + _admin_status((task_map.get(ref) or {}).get("manifest", {}).get("task_type") or (task_map.get(ref) or {}).get("kind", "draft")) + "</td><td>" + _admin_escape((task_map.get(ref) or {}).get("manifest", {}).get("points") if (task_map.get(ref) or {}).get("manifest", {}).get("points") is not None else "—") + "</td><td>" + _admin_escape((task_map.get(ref) or {}).get("manifest", {}).get("time_limit_seconds", "—")) + " sec</td><td><a class='button secondary small' href='/admin/tasks'>Open task registry</a></td></tr>" for ref in contest.task_refs) or "<tr><td colspan='5' class='empty'>No problems yet. Add the first one below.</td></tr>"
    if not platform.policy.global_task_library_enabled:
        rows = rows.replace("<td><a class='button secondary small' href='/admin/tasks'>Open task registry</a></td>", "<td><span class='hint'>Managed in contest</span></td>")
    task_types = "<option value='code_training'>Code (judged) — source code against tests</option><option value='training_code'>AI training code — train and score an artifact</option><option value='model_prediction'>Model / prediction — upload a file or model</option><option value='multiple_choice'>Quiz — multiple-choice questions</option><option value='agent_arena'>Agent arena — submissions play each other</option><option value='agent_environment'>Agent environment — hidden scenarios</option>"
    content = "<div class='page-head'><div><p class='eyebrow'>Contest workspace</p><h2>" + _admin_escape(contest.name) + "</h2><p class='hint mono'>" + _admin_escape(contest.contest_id) + " · " + _admin_escape(contest.status) + "</p></div><a class='button secondary' href='/admin/contests'>Back to contests</a></div><section class='section'><div class='section-head'><div><h2>Problems</h2><p>Define tasks the same way as Brunost: title, slug, type, preset, time limit, and points.</p></div></div><div class='table-wrap'><table><thead><tr><th>Problem</th><th>Type</th><th>Points</th><th>Time limit</th><th></th></tr></thead><tbody>" + rows + "</tbody></table></div></section><section class='card form-card section'><div class='section-head'><div><p class='eyebrow'>Problem authoring</p><h2>Add a problem</h2><p>Creating a problem also creates a starter Judge package. Open the task registry to replace its evaluator and assets.</p></div></div><form class='stack' method='post' action='/admin/contests/" + quote(contest.contest_id) + "/tasks"><div class='form-grid'><label>Problem title<input name='title' placeholder='Maximum subarray' required></label><label>Slug<input name='slug' placeholder='maximum-subarray' required></label></div><label>Task type<select name='task_type'>" + task_types + "</select></label><div class='form-grid'><label>Competition preset<select name='template_key'><option value=''>No preset</option><option value='ioi'>IOI / subtasks</option><option value='icpc'>ICPC / batch judging</option><option value='ioai-model'>IOAI / model prediction</option><option value='quiz'>Quiz / multiple choice</option></select></label><label>Time limit (seconds)<input name='time_limit' type='number' min='1' value='900'></label></div><label>Points<input name='points' type='number' min='0' placeholder='100'></label><button class='button' type='submit'>Add problem</button></form></section>"
    return _admin_page("Contest workspace", content, user=user, active="contests")


@app.post("/admin/contests/{contest_id}/tasks")
def admin_contest_task_create(request: Request, contest_id: str, title: str = Form(...), slug: str = Form(...), task_type: str = Form("code_training"), template_key: str = Form(""), time_limit: str = Form("900"), points: str = Form("")):
    user, response = _admin_user_or_redirect(request)
    if response:
        return response
    contest = store.get_contest(contest_id)
    if contest is None:
        return HTMLResponse(_admin_page("Contest not found", "<div class='card notice error'>This contest does not exist.</div>", user=user, active="contests"), status_code=404)
    try:
        task_ref = _admin_register_task(contest_id, title=title, slug=slug, task_type=task_type, template_key=template_key, time_limit=time_limit, points=points)
        refs = tuple(list(contest.task_refs) + ([task_ref] if task_ref not in contest.task_refs else []))
        platform.create_contest(Contest(contest.contest_id, contest.name, refs, contest.status, contest.metadata), actor=user)
    except Exception as exc:  # noqa: BLE001 - surface task authoring errors in the UI
        content = "<div class='card notice error'>Problem creation failed: " + _admin_escape(exc) + "</div><p><a class='button secondary' href='/admin/contests/" + quote(contest_id) + "'>Go back</a></p>"
        return HTMLResponse(_admin_page("Contest workspace", content, user=user, active="contests"), status_code=400)
    return RedirectResponse("/admin/contests/" + quote(contest_id), status_code=303)


@app.get("/admin/workers", response_class=HTMLResponse)
def admin_workers(request: Request):
    user, response = _admin_user_or_redirect(request)
    if response:
        return response
    workers = _admin_judge_snapshot().get("workers") or []
    rows = "".join("<tr><td><strong>" + _admin_escape(item.get("worker_id")) + "</strong><div class='hint mono'>" + _admin_escape((item.get("metadata") or {}).get("hostname", "")) + "</div></td><td>" + _admin_status("draining" if item.get("draining") else item.get("status", "unknown")) + "</td><td>" + _admin_escape(", ".join(item.get("queues") or [])) + "</td><td>" + _admin_escape(", ".join(item.get("resource_classes") or [])) + "</td><td>" + _admin_escape(", ".join(item.get("capabilities") or []) or "—") + "</td><td>" + _admin_escape(item.get("region") or "—") + "</td><td>" + _worker_actions(item) + "</td></tr>" for item in workers) or "<tr><td colspan='7' class='empty'>No workers enrolled yet. Enroll nodes through brunostctl.</td></tr>"
    operations = store.list_worker_operations(limit=30)
    operation_rows = "".join("<tr><td class='mono'>" + _admin_escape(operation.requested_at) + "</td><td><strong>" + _admin_escape(operation.worker_id) + "</strong></td><td>" + _admin_status(operation.action) + "</td><td>" + _admin_status(operation.status) + "</td><td>" + _admin_escape(operation.actor_email) + "</td><td>" + _admin_escape(operation.reason) + ("<div class='operation-error'>" + _admin_escape(operation.error) + "</div>" if operation.error else "") + "</td></tr>" for operation in operations) or "<tr><td colspan='6' class='empty'>No worker operations recorded yet.</td></tr>"
    message = request.query_params.get("message", "").strip()
    notice = "<div class='notice'>" + _admin_escape(message) + "</div>" if message else ""
    content = notice + "<div class='page-head'><div><p class='eyebrow'>Judge fleet</p><h2>Workers</h2><p>Pause new work, resume a drained worker, or revoke access. Every control action requires a reason and is recorded below.</p></div><a class='button secondary' href='/admin'>Refresh overview</a></div><div class='card section'><div class='section-head'><div><h2>Worker controls</h2><p>Pausing lets active work finish. Revoking a credential is an emergency access action and requires explicit confirmation.</p></div></div><div class='table-wrap'><table><thead><tr><th>Worker</th><th>Status</th><th>Queues</th><th>Resources</th><th>Capabilities</th><th>Region</th><th>Controls</th></tr></thead><tbody>" + rows + "</tbody></table></div></div><section class='section'><div class='section-head'><div><h2>Operation history</h2><p>Recent worker changes made from this control room.</p></div></div><div class='table-wrap'><table><thead><tr><th>Requested</th><th>Worker</th><th>Action</th><th>Result</th><th>Operator</th><th>Reason</th></tr></thead><tbody>" + operation_rows + "</tbody></table></div></section>"
    return _admin_page("Workers", content, user=user, active="workers")


@app.post("/admin/workers/{worker_id:path}/action", response_class=HTMLResponse)
def admin_worker_action(request: Request, worker_id: str, action: str = Form(...), reason: str = Form(...), confirm_text: str = Form("")):
    user, response = _admin_user_or_redirect(request)
    if response:
        return response
    worker_id = worker_id.strip()
    action = action.strip().lower()
    reason = reason.strip()
    if action not in {"pause", "resume", "revoke"}:
        detail = "Unsupported worker action."
    elif not worker_id:
        detail = "Worker ID is required."
    elif not reason:
        detail = "A reason is required for every worker operation."
    elif action == "revoke" and confirm_text.strip().upper() != "REVOKE":
        detail = "Type REVOKE to confirm credential revocation."
    else:
        detail = ""
    if detail:
        content = "<div class='card notice error'>" + _admin_escape(detail) + "</div><p><a class='button secondary' href='/admin/workers'>Back to workers</a></p>"
        return HTMLResponse(_admin_page("Worker operation", content, user=user, active="workers"), status_code=422)

    operation_id = str(uuid.uuid4())
    requested_at = datetime.now(UTC).isoformat()
    try:
        result = judge.revoke_worker_credential(worker_id) if action == "revoke" else judge.drain_worker(worker_id, draining=action == "pause")
    except Exception as exc:  # noqa: BLE001 - preserve failed operator actions for incident review
        operation = WorkerOperation(operation_id, worker_id, action, "failed", user.user_id, user.email, reason[:500], requested_at, datetime.now(UTC).isoformat(), {}, str(exc)[:2000])
        store.record_worker_operation(operation)
        content = "<div class='card notice error'><strong>Worker operation failed.</strong><br>" + _admin_escape(exc) + "</div><p><a class='button secondary' href='/admin/workers'>Back to workers</a></p>"
        return HTMLResponse(_admin_page("Worker operation", content, user=user, active="workers"), status_code=502)
    operation = WorkerOperation(operation_id, worker_id, action, "succeeded", user.user_id, user.email, reason[:500], requested_at, datetime.now(UTC).isoformat(), result, None)
    store.record_worker_operation(operation)
    label = "revoked" if action == "revoke" else "paused" if action == "pause" else "resumed"
    return RedirectResponse("/admin/workers?message=" + quote("Worker " + worker_id + " " + label + "."), status_code=303)


@app.get("/admin/evaluations", response_class=HTMLResponse)
def admin_evaluations(request: Request):
    user, response = _admin_user_or_redirect(request)
    if response:
        return response
    executions = _admin_judge_snapshot().get("executions") or []
    rows = "".join("<tr><td class='mono'>" + _admin_escape(item.get("execution_id")) + "</td><td>" + _admin_escape(item.get("task_ref")) + "</td><td>" + _admin_status(item.get("status", "unknown")) + "</td><td>" + _admin_escape(item.get("queue", "default")) + "</td><td>" + _admin_escape(item.get("resource_class", "cpu")) + "</td><td>" + _admin_escape(item.get("score") if item.get("score") is not None else "—") + "</td><td>" + ("<form method='post' action='/admin/evaluations/" + quote(str(item.get("execution_id"))) + "/cancel'><button class='button danger small' type='submit'>Cancel</button></form>" if item.get("status") in {"queued", "running"} else "—") + "</td></tr>" for item in executions) or "<tr><td colspan='7' class='empty'>No evaluations yet.</td></tr>"
    content = "<div class='page-head'><div><p class='eyebrow'>Judge execution plane</p><h2>Evaluations</h2><p>Every submission, queue, resource class, score, and failure state.</p></div></div><div class='table-wrap'><table><thead><tr><th>Evaluation</th><th>Task</th><th>Status</th><th>Queue</th><th>Resource</th><th>Score</th><th>Action</th></tr></thead><tbody>" + rows + "</tbody></table></div>"
    return _admin_page("Evaluations", content, user=user, active="evaluations")


@app.post("/admin/evaluations/{evaluation_id}/cancel")
def admin_cancel_evaluation(request: Request, evaluation_id: str):
    user, response = _admin_user_or_redirect(request)
    if response:
        return response
    try:
        judge.cancel(evaluation_id)
    except Exception:
        pass
    return RedirectResponse("/admin/evaluations", status_code=303)


@app.get("/admin/definitions", response_class=HTMLResponse)
def admin_definitions(request: Request):
    user, response = _admin_user_or_redirect(request)
    if response:
        return response
    data = _admin_judge_snapshot()
    agents = data.get("agents") or []
    games = data.get("games") or []
    agent_rows = "".join("<tr><td>" + _admin_escape(item.get("agent_id")) + "</td><td>" + _admin_escape(item.get("name")) + "</td><td>" + _admin_escape(item.get("protocol", "stdio")) + "</td><td>" + _admin_status("definition") + "</td></tr>" for item in agents) or "<tr><td colspan='4' class='empty'>No agents registered.</td></tr>"
    game_rows = "".join("<tr><td>" + _admin_escape(item.get("game_id")) + "</td><td>" + _admin_escape(item.get("name")) + "</td><td>" + _admin_escape(item.get("task_ref")) + "</td><td>" + _admin_escape(item.get("seats", "—")) + "</td></tr>" for item in games) or "<tr><td colspan='4' class='empty'>No games registered.</td></tr>"
    content = "<div class='page-head'><div><p class='eyebrow'>Judge extensions</p><h2>Agents & games</h2><p>Declare agent and match definitions. Actual execution requires the corresponding runner plugin.</p></div></div><div class='grid two'><section class='card'><h2>Register agent</h2><form class='stack' method='post' action='/admin/definitions/agents'><label>Agent ID<input name='agent_id' required placeholder='agent/model-v1'></label><label>Name<input name='name' required placeholder='Forecast agent'></label><label>Protocol<input name='protocol' value='stdio'></label><label>Required capabilities<input name='required_capabilities' placeholder='gpu, cuda'></label><button class='button' type='submit'>Register agent</button></form></section><section class='card'><h2>Register game</h2><form class='stack' method='post' action='/admin/definitions/games'><label>Game ID<input name='game_id' required placeholder='game/strategy-v1'></label><label>Name<input name='name' required placeholder='Strategy match'></label><label>Task reference<input name='task_ref' required placeholder='game/task-v1'></label><label>Seats<input name='seats' type='number' value='2' min='2' max='64'></label><button class='button' type='submit'>Register game</button></form></section></div><div class='grid two section'><section><div class='section-head'><h2>Registered agents</h2></div><div class='table-wrap'><table><thead><tr><th>ID</th><th>Name</th><th>Protocol</th><th>State</th></tr></thead><tbody>" + agent_rows + "</tbody></table></div></section><section><div class='section-head'><h2>Registered games</h2></div><div class='table-wrap'><table><thead><tr><th>ID</th><th>Name</th><th>Task</th><th>Seats</th></tr></thead><tbody>" + game_rows + "</tbody></table></div></section></div>"
    return _admin_page("Agents & games", content, user=user, active="definitions")


@app.post("/admin/definitions/agents")
def admin_agent_create(request: Request, agent_id: str = Form(...), name: str = Form(...), protocol: str = Form("stdio"), required_capabilities: str = Form("")):
    user, response = _admin_user_or_redirect(request)
    if response:
        return response
    try:
        judge.register_agent(agent_id=agent_id.strip(), name=name.strip(), protocol=protocol.strip(), required_capabilities=[value.strip() for value in required_capabilities.split(",") if value.strip()])
    except Exception as exc:  # noqa: BLE001 - show Judge validation in the operator UI
        content = "<div class='card notice error'>Agent registration failed: " + _admin_escape(exc) + "</div><p><a class='button secondary' href='/admin/definitions'>Go back</a></p>"
        return HTMLResponse(_admin_page("Agents & games", content, user=user, active="definitions"), status_code=400)
    return RedirectResponse("/admin/definitions", status_code=303)


@app.post("/admin/definitions/games")
def admin_game_create(request: Request, game_id: str = Form(...), name: str = Form(...), task_ref: str = Form(...), seats: int = Form(2)):
    user, response = _admin_user_or_redirect(request)
    if response:
        return response
    try:
        judge.register_game(game_id=game_id.strip(), name=name.strip(), task_ref=task_ref.strip(), seats=seats)
    except Exception as exc:  # noqa: BLE001 - show Judge validation in the operator UI
        content = "<div class='card notice error'>Game registration failed: " + _admin_escape(exc) + "</div><p><a class='button secondary' href='/admin/definitions'>Go back</a></p>"
        return HTMLResponse(_admin_page("Agents & games", content, user=user, active="definitions"), status_code=400)
    return RedirectResponse("/admin/definitions", status_code=303)
'''


def _python_files(project_name: str) -> dict[str, str]:
    return {
        "README.md": f"""# {project_name}\n\nGenerated Brunost Platform Kit application.\n\n```bash\npython -m venv .venv && source .venv/bin/activate\npip install -e .\nexport BRUNOST_JUDGE_URL=http://127.0.0.1:8787\nexport BRUNOST_JUDGE_API_TOKEN=replace-with-judge-token\nexport BRUNOST_JUDGE_CALLBACK_SECRET=replace-with-callback-secret\nexport BRUNOST_PLATFORM_CALLBACK_TOKEN=replace-with-callback-token\nexport BRUNOST_DEFAULT_ADMIN_EMAIL=admin@example.org\nexport BRUNOST_DEFAULT_ADMIN_PASSWORD=change-me-now\nuvicorn app.main:app --host 127.0.0.1 --port 3000\n```\n\nOpen http://127.0.0.1:3000 for the landing page, then sign in at /login with\nthe default admin credentials and immediately change the password. Use /admin\nfor the operator dashboard. It includes task packages, contests, workers,\nevaluations, agent/game definitions, and the platform JSON API.\nReplace the UI or connect an external identity provider without changing the\nJudge execution boundary.\n""",
        ".env.example": "BRUNOST_JUDGE_URL=http://127.0.0.1:8787\nBRUNOST_JUDGE_API_TOKEN=\nBRUNOST_JUDGE_IMAGE=ghcr.io/mlgorithm/brunost-judge@sha256:<64-hex-digest>\nBRUNOST_JUDGE_CALLBACK_SECRET=replace-with-judge-callback-secret\nBRUNOST_PLATFORM_CALLBACK_URL=http://127.0.0.1:3000/api/judge/callback\nBRUNOST_PLATFORM_CALLBACK_TOKEN=replace-with-callback-token\nBRUNOST_PLATFORM_DATABASE=platform.db\nBRUNOST_SUBMISSION_ROOT=submissions\nBRUNOST_DEFAULT_ADMIN_EMAIL=admin@example.org\nBRUNOST_DEFAULT_ADMIN_PASSWORD=change-me-now\nBRUNOST_DEFAULT_ADMIN_NAME=Country operator\n",
        "pyproject.toml": """[project]\nname = \"brunost-platform-app\"\nversion = \"0.1.0\"\nrequires-python = \">=3.11\"\ndependencies = [\"fastapi>=0.115,<1\", \"uvicorn[standard]>=0.30,<1\", \"python-multipart>=0.0.9,<1\", \"brunost-platform-kit[postgres]>=0.1\"]\n\n[build-system]\nrequires = [\"setuptools>=68\"]\nbuild-backend = \"setuptools.build_meta\"\n""",
        "Dockerfile": """FROM python:3.12-slim\nWORKDIR /app\nCOPY . .\nRUN pip install --no-cache-dir .\nEXPOSE 3000\nCMD [\"uvicorn\", \"app.main:app\", \"--host\", \"0.0.0.0\", \"--port\", \"3000\"]\n""",
        "docker-compose.yml": """services:\n  platform:\n    build: .\n    ports: [\"3000:3000\"]\n    environment:\n      BRUNOST_JUDGE_URL: http://judge:8787\n      BRUNOST_PLATFORM_CALLBACK_URL: http://platform:3000/api/judge/callback\n      BRUNOST_PLATFORM_CALLBACK_TOKEN: ${BRUNOST_PLATFORM_CALLBACK_TOKEN:?set a callback bearer token}\n      BRUNOST_JUDGE_CALLBACK_SECRET: ${BRUNOST_JUDGE_CALLBACK_SECRET:?set a callback signing secret}\n    depends_on: [judge]\n  judge:\n    image: ${BRUNOST_JUDGE_IMAGE:?set BRUNOST_JUDGE_IMAGE to a digest-pinned image}\n    command: [\"server\", \"--host\", \"0.0.0.0\", \"--port\", \"8787\"]\n    environment:\n      BRUNOST_JUDGE_CALLBACK_SIGNING_SECRET: ${BRUNOST_JUDGE_CALLBACK_SECRET:?set a callback signing secret}\n      BRUNOST_JUDGE_CALLBACK_HOSTS: platform\n    ports: [\"8787:8787\"]\n""",
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
            "import os\n\nfrom fastapi import FastAPI, HTTPException\nfrom pydantic import BaseModel, Field\n\nfrom brunost_platform.application import PlatformApplication\nfrom brunost_platform.gateway import gateway_from_environment\nfrom brunost_platform.models import Contest, Submission\nfrom brunost_platform.postgres import PostgresPlatformStore\nfrom brunost_platform.store import SQLitePlatformStore",
        )
        files["app/main.py"] = files["app/main.py"].replace(
            "judge = gateway_from_environment()",
            "judge = gateway_from_environment()\ndatabase = os.environ.get(\"BRUNOST_PLATFORM_DATABASE\", \"platform.db\")\nstore = PostgresPlatformStore(database) if database.startswith((\"postgres://\", \"postgresql://\")) else SQLitePlatformStore(database)\nplatform = PlatformApplication(judge, store=store)",
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
        files["app/main.py"] += _admin_ui_appendix()
        files["app/main.py"] = files["app/main.py"].replace('+ "/tasks"><div', '+ "/tasks\'><div')
        files[".env.example"] += "BRUNOST_PLATFORM_EDITION=standalone\nBRUNOST_PLATFORM_FEATURES=\n"
        files[".env.example"] += "BRUNOST_PLATFORM_SERVICE_TOKEN=\n"
        files["docker-compose.yml"] = files["docker-compose.yml"].replace(
            "      BRUNOST_JUDGE_CALLBACK_SECRET: ${BRUNOST_JUDGE_CALLBACK_SECRET:?set a callback signing secret}\n",
            "      BRUNOST_JUDGE_CALLBACK_SECRET: ${BRUNOST_JUDGE_CALLBACK_SECRET:?set a callback signing secret}\n      BRUNOST_PLATFORM_EDITION: ${BRUNOST_PLATFORM_EDITION:-standalone}\n      BRUNOST_PLATFORM_FEATURES: ${BRUNOST_PLATFORM_FEATURES:-}\n      BRUNOST_PLATFORM_SERVICE_TOKEN: ${BRUNOST_PLATFORM_SERVICE_TOKEN:-}\n",
        )
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
        files["src/server.ts"] = files["src/server.ts"].replace(
            'const statePath = process.env.BRUNOST_PLATFORM_DATABASE ?? "platform.json";',
            'const statePath = process.env.BRUNOST_PLATFORM_DATABASE ?? "platform.json";\\nconst edition = process.env.BRUNOST_PLATFORM_EDITION ?? "standalone";\\nconst advanced = edition === "advanced";',
        ).replace(
            'role === "admin" || role === "organizer"',
            'role === "admin" || (advanced && ["organizer", "teacher", "contest_creator"].includes(role))',
        ).replace(
            'state.users.length ? ["contestant"] : ["admin"]',
            'state.users.length ? [advanced ? "contestant" : "student"] : ["admin"]',
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
