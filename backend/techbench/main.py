from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
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
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    code = create_pair_code(body.alias, body.location)
    cmd = f"python agent/techbench_agent.py --server http://<bench-host>:8000 --code {code}"
    return PairResponse(code=code, agent_command=cmd)


@app.post("/api/agent/register")
def api_agent_register(body: AgentRegister):
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
        candidate = FRONTEND_DIST / path
        if path and candidate.exists() and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
