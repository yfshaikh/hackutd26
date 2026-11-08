"""Command-center backend. Implements the contract in console/API.md.

Real cluster state in, real attacker/defender actions out. Session-cookie auth,
server-side role enforcement, SSE live feed.

Layout of this file:
  * app + CORS + router includes (WS-A metrics, WS-B incident routes)
  * _telemetry_loop + the startup hook that launches the two background loops
    (telemetry every ~2 s, defender.detection_loop every ~4 s)
  * route groups, each under a banner: Auth / Dashboard (snapshot + /events SSE) /
    Approvals / Messages / Users / Attack panel / Attacker transcript / health
The defender's own logic lives in defender.py; the attack chain in attacks.py.

In plain terms: this is the web server (built with FastAPI) that both the defender
console and the attacker app talk to. It does three jobs:
  1. Serves the API — each `@app.get/post(...)` below is one URL it answers.
  2. Runs two background loops forever once it starts up: a TELEMETRY loop that reads
     the GPU + cluster every ~2 s, and defender.detection_loop that checks for the
     attack every ~4 s and wakes the agent. These run on their own, no request needed.
  3. Streams live updates to the browser over SSE (the /events feed).
CORS (the middleware just below) is a browser security rule: a page served from one
origin can't call a server on another origin unless the server opts in. We opt in for
exactly the console and attacker app origins so those two pages can reach this API.
"""
from __future__ import annotations

import asyncio
import contextlib
import fcntl
import hashlib
import json
import os
import tempfile
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from . import attacks, config, db, defender
from .auth import COOKIE_NAME, auth, current_user, require_roles
from .cluster import build_cluster, read_gpus, seed_assets
from .hub import store
from .routes_defender import router as defender_router
from .routes_cluster import router as cluster_router
from .routes_incident import router as incident_router
from .routes_loot import router as loot_router
from .transcript import transcript
from .models import (
    AttackResult,
    LoginBody,
    MessageBody,
    NewUser,
    Session,
    Snapshot,
    User,
)

app = FastAPI(title="HackUTD command center")

app.add_middleware(
    CORSMiddleware,
    # Console (defender, uses cookies) + the separate attacker app (Task 2, no cookies).
    allow_origins=[config.CONSOLE_ORIGIN, config.ATTACKER_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# WS-B: additive incident-dashboard routes (record / scope / roles / chat).
app.include_router(incident_router)
# WS-A: additive defender metrics route (GET /defender/metrics).
app.include_router(defender_router)
# Read-only pod inspection for the floor drawer (specs + logs).
app.include_router(cluster_router)
# Attacker app's live loot + victim counters (GET /attack/loot; no auth, by design).
app.include_router(loot_router)

_bg_tasks: list[asyncio.Task] = []
_singleton_lock = None


def _acquire_singleton_lock() -> None:
    """Refuse to run a second detector/agent loop for this checkout.

    Multiple `uvicorn app.main:app` processes can end up serving :8000 (a stray
    `uv run` left in another terminal is enough). Each runs its own detection loop
    against the same cluster, so two Advisors race: one deletes the miner, the
    other's `quarantine_pod` then gets `Not Found` and narrates a self-termination
    that never happened. One flock per checkout prevents that. The OS releases it
    when the process exits, so a crash never leaves it stuck.
    """
    global _singleton_lock
    key = hashlib.sha1(str(config.BACKEND_DIR).encode()).hexdigest()[:12]
    path = Path(tempfile.gettempdir()) / f"hackutd-backend-{key}.lock"
    fh = path.open("w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        raise RuntimeError(
            "Another backend is already running for this checkout. Stop it before "
            "starting a second one (two detection loops race on the same cluster)."
        ) from None
    fh.write(str(os.getpid()))
    fh.flush()
    _singleton_lock = fh


async def _telemetry_loop() -> None:
    """Every ~2 s: real nvidia-smi + cluster state -> rolling GPU history + cluster event."""
    while True:
        try:
            gpus, total = await asyncio.to_thread(read_gpus)
            store.gpu_history.append(round(total, 1))
            cluster = await asyncio.to_thread(build_cluster, list(store.gpu_history), gpus)
            store.set_cluster(cluster)
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(2)


@app.on_event("startup")
async def _startup() -> None:
    _acquire_singleton_lock()
    loop = asyncio.get_running_loop()
    store.bind_loop(loop)
    transcript.bind_loop(loop)
    auth.seed_admin()
    try:
        for a in await asyncio.to_thread(seed_assets):
            store.assets[a.id] = a
    except Exception:  # noqa: BLE001
        pass
    if not defender.nemotron_configured():
        store.add_timeline(
            kind="system",
            actor="System",
            text="Nemotron not configured: set OPENROUTER_API_KEY or NVIDIA_API_KEY in backend/.env. "
            "Detection is live; the defender agent stays dormant until a key is set.",
            severity="medium",
        )
    else:
        store.add_timeline(
            kind="system", actor="System",
            text=f"Defender online: Nemotron model {config.NEMOTRON_MODEL} ready.", severity="info",
        )
    # Two long-lived background loops: poll GPU/cluster telemetry, and run the
    # defender's detect -> escalate cycle. Both are cancelled on shutdown.
    _bg_tasks.append(asyncio.create_task(_telemetry_loop()))
    _bg_tasks.append(asyncio.create_task(defender.detection_loop()))


@app.on_event("shutdown")
async def _shutdown() -> None:
    for t in _bg_tasks:
        t.cancel()
    for t in _bg_tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await t


# ---- Auth -----------------------------------------------------------------
@app.post("/auth/login", response_model=Session)
def login(body: LoginBody, response: Response) -> Session:
    user = auth.authenticate(body.email, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = auth.start_session(user.id)
    response.set_cookie(
        key=COOKIE_NAME, value=token, httponly=True, samesite="lax", secure=False, path="/"
    )
    return Session(user=user)


@app.get("/auth/me", response_model=Session)
def me(user: User = Depends(current_user)) -> Session:
    return Session(user=user)


@app.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response) -> Response:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        auth.end_session(token)
    response.delete_cookie(COOKIE_NAME, path="/")
    response.status_code = 204
    return response


# ---- Dashboard ------------------------------------------------------------
@app.get("/snapshot", response_model=Snapshot)
def snapshot(user: User = Depends(current_user)) -> Snapshot:
    return store.snapshot()


@app.get("/events")
async def events(request: Request, user: User = Depends(current_user)) -> StreamingResponse:
    queue = store.subscribe()

    async def gen():
        try:
            first = {"type": "snapshot", "snapshot": store.snapshot().model_dump(exclude_none=True)}
            yield f"data: {json.dumps(first)}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            store.unsubscribe(queue)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# ---- Incident history (past incidents, archived on resolve/reset) ---------
@app.get("/incidents")
def list_incidents(user: User = Depends(current_user)) -> list[dict]:
    """Newest first; summary fields only. Backed by SQLite, not the live store."""
    return db.list_incidents()


@app.get("/incidents/{incident_id}")
def get_incident(incident_id: str, user: User = Depends(current_user)) -> dict:
    """One archived incident with its full record + timeline."""
    incident = db.get_incident(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="No such incident")
    return incident


# ---- Approvals ------------------------------------------------------------
@app.post("/approvals/{approval_id}/approve")
async def approve(approval_id: str, user: User = Depends(require_roles("admin", "responder", "approver"))):
    return await _decide(approval_id, approved=True, user=user)


@app.post("/approvals/{approval_id}/deny")
async def deny(approval_id: str, user: User = Depends(require_roles("admin", "responder", "approver"))):
    return await _decide(approval_id, approved=False, user=user)


async def _decide(approval_id: str, *, approved: bool, user: User):
    from .models import now_iso

    approval = store.approvals.get(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="No such approval")
    if approval.status != "pending":
        raise HTTPException(status_code=409, detail=f"Approval already {approval.status}")
    approval.status = "approved" if approved else "denied"
    approval.decidedBy = user.name
    approval.decidedAt = now_iso()
    store.upsert_approval(approval)

    pending = defender.pending_actions.pop(approval_id, None)
    if approved and pending:
        tool, args, _reason = pending
        try:
            await asyncio.to_thread(defender.run_tool_approved, tool, args, approval_id, user.name)
        except Exception as e:  # noqa: BLE001
            store.add_timeline(kind="system", actor="System",
                               text=f"Approved action {tool} failed: {e}", severity="high")
    else:
        store.add_timeline(
            kind="human", actor=user.name,
            text=f"{'Approved' if approved else 'Denied'}: {approval.action}.",
            severity="info",
        )
        if not approved:
            defender.record_action(f"Human denied: {approval.action}.", by=user.name)
    return approval


# ---- Messages -------------------------------------------------------------
@app.post("/messages")
def post_message(body: MessageBody, user: User = Depends(require_roles("admin", "responder", "operator"))):
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    return store.add_timeline(kind="human", actor=user.name, text=text)


# ---- Users ----------------------------------------------------------------
@app.get("/users", response_model=list[User])
def list_users(user: User = Depends(require_roles("admin"))) -> list[User]:
    return auth.list_users()


@app.post("/users", response_model=User)
def add_user(body: NewUser, user: User = Depends(require_roles("admin"))) -> User:
    return auth.create_user(name=body.name, email=body.email, role=body.role)


# ---- Attack panel (no auth: the judges drive it) --------------------------
@app.get("/attack")
def attack_steps():
    return store.attack_list()


@app.post("/attack/{step}", response_model=AttackResult)
async def run_attack(step: str) -> AttackResult:
    if step not in ("gain-access", "start-miner", "steal-weights", "persistence", "ddos"):
        raise HTTPException(status_code=404, detail=f"Unknown attack step '{step}'")
    current = store.attack[step].status
    if current == "locked":
        return AttackResult(
            ok=False, step=step,
            message="This step is locked — run the previous step first.",
            attack=store.attack_list(),
        )
    store.set_attack_status(step, "running")
    store.publish_attack()
    result = await asyncio.to_thread(attacks.run_step, step)
    if not result.ok and current != "done":
        store.set_attack_status(step, "ready")
        store.publish_attack()
    return result


@app.post("/reset", response_model=AttackResult)
async def reset() -> AttackResult:
    defender.reset_detection_state()
    result = await asyncio.to_thread(attacks.reset)
    return result


# ---- Attacker transcript (the attacker app's live feed; no auth) ----------
@app.get("/attack/transcript")
def attack_transcript():
    """Full ordered transcript so far: {entries, step}."""
    return {"entries": transcript.history(), "step": transcript.current_step}


@app.get("/attack/recon")
async def attack_recon():
    """Live recon for the attacker app: exposed Jupyter, stolen-identity rules, GPU."""
    return await asyncio.to_thread(attacks.recon)


@app.get("/attack/stream")
async def attack_stream(request: Request) -> StreamingResponse:
    """SSE stream of transcript entries. Sends history first, then live deltas."""
    queue = transcript.subscribe()

    async def gen():
        try:
            first = {"type": "history", "entries": transcript.history(),
                     "step": transcript.current_step}
            yield f"data: {json.dumps(first)}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            transcript.unsubscribe(queue)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.get("/healthz")
def healthz():
    return {"ok": True, "nemotron": defender.nemotron_configured()}
