from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from techbench import __version__
from techbench.models import (
    AgentRegister,
    AgentSnapshotIn,
    AgentTelemetryIn,
    NoteIn,
    PairRequest,
    PairResponse,
    RemediateIn,
    SessionIn,
)
from techbench.report import render_markdown_report
from techbench.security import (
    MAX_BODY_BYTES,
    SECURITY_HEADERS,
    SESSION_COOKIE,
    RateLimiter,
    client_ip,
    drop_session,
    ensure_bench_token,
    host_header_ok,
    is_loopback_ip,
    issue_session,
    pair_agent_command,
    safe_dist_file,
    same_origin_ok,
    session_ok,
    token_ok,
)
from techbench.store import (
    FLEET_CHANNEL,
    add_note,
    boot_bench,
    create_pair_code,
    fleet_summary,
    get_machine,
    ingest_agent_snapshot,
    ingest_agent_telemetry,
    list_machines,
    machine_card,
    machine_history,
    next_ticket,
    register_agent,
    remediate,
    run_scan,
    seed_demo_fleet,
    state,
    telemetry_loop,
)

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
DEBUG = os.environ.get("TECHBENCH_DEBUG") == "1"
CORS_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "TECHBENCH_CORS",
        "http://127.0.0.1:8000,http://localhost:8000,http://127.0.0.1:5173,http://localhost:5173",
    ).split(",")
    if o.strip()
]
_pair_limit = RateLimiter(10, 60)
_register_limit = RateLimiter(20, 60)
_agent_post_limit = RateLimiter(120, 60)
_session_limit = RateLimiter(20, 60)

PUBLIC_API = {
    ("GET", "/api/health"),
    ("POST", "/api/session"),
    ("POST", "/api/session/loopback"),
    ("POST", "/api/session/logout"),
}


def _bench_token() -> str:
    return ensure_bench_token()


def _authorized(request: Request) -> bool:
    path = request.url.path
    method = request.method.upper()
    if (method, path) in PUBLIC_API or not path.startswith("/api"):
        return True
    token = _bench_token()
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer ") and token_ok(auth[7:].strip(), token):
        return True
    return session_ok(request.cookies.get(SESSION_COOKIE))


def _set_session_cookie(response: Response, sid: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        sid,
        httponly=True,
        samesite="strict",
        secure=False,
        max_age=12 * 3600,
        path="/",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_bench_token()
    boot_bench()
    task = asyncio.create_task(telemetry_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="TECH-BENCH",
    description="Virtual tech bench for remote PC diagnostics.",
    version=__version__,
    lifespan=lifespan,
    docs_url="/docs" if DEBUG else None,
    redoc_url=None,
    openapi_url="/openapi.json" if DEBUG else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-Techbench"],
)


@app.middleware("http")
async def harden(request: Request, call_next):
    if not host_header_ok(request.headers.get("host")):
        return JSONResponse({"detail": "Invalid host"}, status_code=400)
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
        return JSONResponse({"detail": "Payload too large"}, status_code=413)
    if not _authorized(request):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    response = await call_next(request)
    for key, value in SECURITY_HEADERS.items():
        response.headers.setdefault(key, value)
    return response


@app.get("/api/health")
def health():
    return {"ok": True, "version": __version__, "auth": "required"}


@app.post("/api/session")
def api_session(body: SessionIn, request: Request, response: Response):
    ip = client_ip(request.client.host if request.client else None)
    if not _session_limit.hit(ip):
        raise HTTPException(429, "Too many login attempts")
    if not token_ok(body.token.strip(), _bench_token()):
        raise HTTPException(401, "Bad token")
    _set_session_cookie(response, issue_session())
    return {"ok": True}


@app.post("/api/session/loopback")
def api_session_loopback(request: Request, response: Response):
    ip = client_ip(request.client.host if request.client else None)
    if not is_loopback_ip(ip) and ip != "testclient":
        raise HTTPException(403, "Loopback session is only available on the bench host")
    if request.headers.get("x-techbench") != "1":
        raise HTTPException(403, "Missing client header")
    origin = request.headers.get("origin")
    if origin and not same_origin_ok(origin, request.headers.get("host")):
        raise HTTPException(403, "Bad origin")
    if not _session_limit.hit(ip):
        raise HTTPException(429, "Too many login attempts")
    _set_session_cookie(response, issue_session())
    return {"ok": True}


@app.post("/api/session/logout")
def api_session_logout(request: Request, response: Response):
    drop_session(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@app.get("/api/machines")
def api_machines():
    return [machine_card(m) for m in list_machines()]


@app.get("/api/fleet")
def api_fleet():
    return fleet_summary()


@app.get("/api/machines/{machine_id}")
def api_machine(machine_id: str):
    try:
        return get_machine(machine_id).model_dump(mode="json")
    except KeyError:
        raise HTTPException(404, "Machine not on the bench")


@app.get("/api/machines/{machine_id}/report")
def api_report(machine_id: str):
    try:
        machine = get_machine(machine_id)
    except KeyError:
        raise HTTPException(404, "Machine not on the bench")
    safe_id = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in machine_id)[:64]
    body = render_markdown_report(machine)
    return PlainTextResponse(
        body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="techbench-{safe_id}.md"'},
    )


@app.get("/api/machines/{machine_id}/telemetry")
def api_telemetry(machine_id: str, limit: int = 120):
    if machine_id not in state.machines:
        raise HTTPException(404, "Unknown machine")
    buf = list(state.telemetry.get(machine_id, []))
    return [s.model_dump(mode="json") for s in buf[-min(limit, 180) :]]


@app.post("/api/machines/{machine_id}/scan")
async def api_scan(machine_id: str):
    if machine_id not in state.machines:
        raise HTTPException(404, "Unknown machine")
    m = await run_scan(machine_id)
    return m.model_dump(mode="json")


@app.post("/api/machines/{machine_id}/remediate")
async def api_remediate(machine_id: str, body: RemediateIn):
    try:
        m = remediate(machine_id, body.finding_id)
    except KeyError:
        raise HTTPException(404, "Unknown machine")
    await state.publish(machine_id, {"type": "machine_update", "machine": m.model_dump(mode="json")})
    return m.model_dump(mode="json")


@app.get("/api/machines/{machine_id}/history")
def api_history(machine_id: str):
    try:
        return machine_history(machine_id)
    except KeyError:
        raise HTTPException(404, "Unknown machine")


@app.post("/api/machines/{machine_id}/notes")
def api_note(machine_id: str, body: NoteIn):
    try:
        note = add_note(machine_id, body.body)
    except KeyError:
        raise HTTPException(404, "Unknown machine")
    return note.model_dump(mode="json")


@app.get("/api/fleet/next")
def api_next(after: str | None = None):
    m = next_ticket(after)
    if m is None:
        raise HTTPException(404, "No bays")
    return machine_card(m)


@app.post("/api/demo/fleet")
def api_demo_fleet():
    created = seed_demo_fleet(reset=True)
    return {"ok": True, "count": len(created)}


@app.post("/api/pair", response_model=PairResponse)
def api_pair(body: PairRequest, request: Request):
    ip = client_ip(request.client.host if request.client else None)
    if not _pair_limit.hit(ip):
        raise HTTPException(429, "Too many pairing requests")
    code = create_pair_code(body.alias, body.location)
    cmd = pair_agent_command(request.headers.get("host"), code)
    return PairResponse(code=code, agent_command=cmd)


@app.post("/api/agent/register")
def api_agent_register(body: AgentRegister, request: Request):
    ip = client_ip(request.client.host if request.client else None)
    if not _register_limit.hit(ip):
        raise HTTPException(429, "Too many register attempts")
    try:
        token, machine = register_agent(body.code, body.inventory)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    return {"token": token, "machine": machine.model_dump(mode="json")}


@app.post("/api/agent/snapshot")
async def api_agent_snapshot(body: AgentSnapshotIn, request: Request):
    ip = client_ip(request.client.host if request.client else None)
    if not _agent_post_limit.hit(ip):
        raise HTTPException(429, "Too many agent posts")
    try:
        m = ingest_agent_snapshot(body.token, body.snapshot)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    await state.publish(m.id, {"type": "machine_update", "machine": m.model_dump(mode="json")})
    return m.model_dump(mode="json")


@app.post("/api/agent/telemetry")
async def api_agent_telemetry(body: AgentTelemetryIn, request: Request):
    ip = client_ip(request.client.host if request.client else None)
    if not _agent_post_limit.hit(ip):
        raise HTTPException(429, "Too many agent posts")
    try:
        m = ingest_agent_telemetry(body.token, body.sample)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    await state.publish(m.id, {"type": "telemetry", "sample": body.sample.model_dump(mode="json")})
    return {"ok": True, "machine_id": m.id}


@app.websocket("/api/ws/machines/{machine_id}")
async def ws_machine(websocket: WebSocket, machine_id: str):
    token = _bench_token()
    auth = websocket.headers.get("authorization", "")
    bearer_ok = auth.startswith("Bearer ") and token_ok(auth[7:].strip(), token)
    cookie_ok = session_ok(websocket.cookies.get(SESSION_COOKIE))
    if not bearer_ok and not cookie_ok:
        await websocket.close(code=4401)
        return
    if machine_id not in state.machines:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    queue = state.subscribe(machine_id)
    try:
        m = get_machine(machine_id)
        await websocket.send_json({"type": "machine_update", "machine": m.model_dump(mode="json")})
        buf = list(state.telemetry.get(machine_id, []))
        if buf:
            await websocket.send_json(
                {"type": "telemetry_history", "samples": [s.model_dump(mode="json") for s in buf[-120:]]}
            )
        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=20)
                await websocket.send_json(payload)
            except TimeoutError:
                await websocket.send_json({"type": "ping"})
    except WebSocketDisconnect:
        pass
    finally:
        state.unsubscribe(machine_id, queue)


@app.websocket("/api/ws/fleet")
async def ws_fleet(websocket: WebSocket):
    token = _bench_token()
    auth = websocket.headers.get("authorization", "")
    bearer_ok = auth.startswith("Bearer ") and token_ok(auth[7:].strip(), token)
    cookie_ok = session_ok(websocket.cookies.get(SESSION_COOKIE))
    if not bearer_ok and not cookie_ok:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    queue = state.subscribe(FLEET_CHANNEL)
    try:
        await websocket.send_json({"type": "fleet", "summary": fleet_summary()})
        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=20)
                await websocket.send_json(payload)
            except TimeoutError:
                await websocket.send_json({"type": "ping", "summary": fleet_summary()})
    except WebSocketDisconnect:
        pass
    finally:
        state.unsubscribe(FLEET_CHANNEL, queue)


if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        safe = safe_dist_file(FRONTEND_DIST, path)
        if safe is not None:
            return FileResponse(safe)
        return FileResponse(
            FRONTEND_DIST / "index.html",
            headers={"Cache-Control": "no-store"},
        )
