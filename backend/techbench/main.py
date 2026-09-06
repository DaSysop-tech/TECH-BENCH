from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from techbench import __version__
from techbench.models import (
    AgentRegister,
    AgentSnapshotIn,
    AgentTelemetryIn,
    PairRequest,
    PairResponse,
    RemediateIn,
)
from techbench.security import RateLimiter, safe_dist_file
from techbench.store import (
    create_pair_code,
    get_machine,
    ingest_agent_snapshot,
    ingest_agent_telemetry,
    list_machines,
    register_agent,
    remediate,
    run_scan,
    seed_demo_fleet,
    seed_local,
    state,
    telemetry_loop,
)

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
BENCH_TOKEN = os.environ.get("TECHBENCH_TOKEN", "")
CORS_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "TECHBENCH_CORS",
        "http://127.0.0.1:8000,http://localhost:8000,http://127.0.0.1:5173,http://localhost:5173",
    ).split(",")
    if o.strip()
]
_pair_limit = RateLimiter(10, 60)
_register_limit = RateLimiter(30, 60)


def _authorized(request: Request) -> bool:
    if not BENCH_TOKEN:
        return True
    path = request.url.path
    if path == "/api/health" or not path.startswith("/api"):
        return True
    auth = request.headers.get("authorization", "")
    return auth == f"Bearer {BENCH_TOKEN}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    seed_local()
    seed_demo_fleet()
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
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def bench_auth(request: Request, call_next):
    if not _authorized(request):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return await call_next(request)


@app.get("/api/health")
def health():
    return {"ok": True, "version": __version__, "machines": len(state.machines)}


@app.get("/api/machines")
def api_machines():
    return [m.model_dump(mode="json") for m in list_machines()]


@app.get("/api/machines/{machine_id}")
def api_machine(machine_id: str):
    try:
        return get_machine(machine_id).model_dump(mode="json")
    except KeyError:
        raise HTTPException(404, "Machine not on the bench")


@app.get("/api/machines/{machine_id}/telemetry")
def api_telemetry(machine_id: str, limit: int = 120):
    if machine_id not in state.machines:
        raise HTTPException(404, "Unknown machine")
    buf = list(state.telemetry.get(machine_id, []))
    return [s.model_dump(mode="json") for s in buf[-limit:]]


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


@app.post("/api/demo/fleet")
def api_demo_fleet():
    created = seed_demo_fleet()
    return {"ok": True, "count": len(created)}


@app.post("/api/pair", response_model=PairResponse)
def api_pair(body: PairRequest):
    if not _pair_limit.hit():
        raise HTTPException(429, "Too many pairing requests")
    code = create_pair_code(body.alias, body.location)
    cmd = f"python agent/techbench_agent.py --server http://BENCH_HOST:8000 --code {code}"
    return PairResponse(code=code, agent_command=cmd)


@app.post("/api/agent/register")
def api_agent_register(body: AgentRegister):
    if not _register_limit.hit():
        raise HTTPException(429, "Too many register attempts")
    try:
        token, machine = register_agent(body.code, body.inventory)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    return {"token": token, "machine": machine.model_dump(mode="json")}


@app.post("/api/agent/snapshot")
async def api_agent_snapshot(body: AgentSnapshotIn):
    try:
        m = ingest_agent_snapshot(body.token, body.snapshot)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    await state.publish(m.id, {"type": "machine_update", "machine": m.model_dump(mode="json")})
    return m.model_dump(mode="json")


@app.post("/api/agent/telemetry")
async def api_agent_telemetry(body: AgentTelemetryIn):
    try:
        m = ingest_agent_telemetry(body.token, body.sample)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    await state.publish(m.id, {"type": "telemetry", "sample": body.sample.model_dump(mode="json")})
    return {"ok": True, "machine_id": m.id}


@app.websocket("/api/ws/machines/{machine_id}")
async def ws_machine(websocket: WebSocket, machine_id: str):
    if BENCH_TOKEN:
        auth = websocket.headers.get("authorization", "")
        qtok = websocket.query_params.get("access_token", "")
        if auth != f"Bearer {BENCH_TOKEN}" and qtok != BENCH_TOKEN:
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


if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        safe = safe_dist_file(FRONTEND_DIST, path)
        if safe is not None:
            return FileResponse(safe)
        return FileResponse(FRONTEND_DIST / "index.html")
