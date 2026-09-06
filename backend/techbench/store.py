from __future__ import annotations

import asyncio
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field

from techbench.diagnostics.collectors import collect_local_snapshot, collect_local_telemetry
from techbench.diagnostics.engine import diagnose, health_score, overall_severity
from techbench.models import (
    Finding,
    Machine,
    MachineKind,
    MachineSnapshot,
    MachineStatus,
    Severity,
    TelemetrySample,
)
from techbench.sim.fleet import FLEET, apply_remediation, snapshot_for


SCAN_STAGES = [
    ("inventory", 8, "Enumerating hardware"),
    ("firmware", 18, "Reading firmware / SMBIOS"),
    ("smart", 32, "Interrogating SMART / NVMe health"),
    ("memory", 46, "Memory pressure & leak analysis"),
    ("thermal", 58, "Mapping thermals and fan curves"),
    ("network", 70, "Network path, DNS, loss"),
    ("process", 82, "Process and signature anomalies"),
    ("events", 92, "Correlating event log faults"),
    ("report", 100, "Writing bench report"),
]


@dataclass
class PairSlot:
    code: str
    alias: str
    location: str
    expires: float


@dataclass
class BenchState:
    machines: dict[str, Machine] = field(default_factory=dict)
    telemetry: dict[str, deque] = field(default_factory=lambda: defaultdict(lambda: deque(maxlen=240)))
    pair_slots: dict[str, PairSlot] = field(default_factory=dict)
    agent_tokens: dict[str, str] = field(default_factory=dict)  # token -> machine_id
    subscribers: dict[str, set[asyncio.Queue]] = field(default_factory=lambda: defaultdict(set))
    remediations: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    sim_overrides: dict[str, MachineSnapshot] = field(default_factory=dict)

    def subscribe(self, machine_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=64)
        self.subscribers[machine_id].add(q)
        return q

    def unsubscribe(self, machine_id: str, q: asyncio.Queue) -> None:
        self.subscribers[machine_id].discard(q)

    async def publish(self, machine_id: str, payload: dict) -> None:
        dead = []
        for q in list(self.subscribers.get(machine_id, ())):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self.subscribers[machine_id].discard(q)


state = BenchState()


def _score_machine(machine: Machine) -> None:
    machine.overall = overall_severity(machine.findings)
    machine.health_score = health_score(machine.findings)
    active = [f for f in machine.findings if not f.remediated]
    machine.open_critical = sum(1 for f in active if f.severity == Severity.critical)
    machine.open_warning = sum(1 for f in active if f.severity == Severity.warning)
    machine.open_info = sum(1 for f in active if f.severity == Severity.info)


def _decorate(machine: Machine, snapshot: MachineSnapshot, findings: list[Finding] | None = None) -> Machine:
    findings = findings if findings is not None else diagnose(snapshot)
    rem = state.remediations.get(machine.id, set())
    present = {f.id for f in findings}
    if machine.findings:
        for old in machine.findings:
            if old.id in rem and old.id not in present:
                copied = old.model_copy()
                copied.remediated = True
                findings.append(copied)
                present.add(old.id)
    for f in findings:
        if f.id in rem:
            f.remediated = True
    rank = {Severity.critical: 0, Severity.warning: 1, Severity.info: 2, Severity.ok: 3}
    findings.sort(key=lambda f: (1 if f.remediated else 0, rank[f.severity], -f.confidence, f.title))
    machine.snapshot = snapshot
    machine.findings = findings
    _score_machine(machine)
    machine.hostname = snapshot.inventory.hostname
    machine.os = snapshot.inventory.os
    machine.last_seen = time.time()
    machine.status = MachineStatus.online
    return machine


def seed_local() -> Machine:
    snap = collect_local_snapshot()
    m = Machine(
        id="local-workstation",
        hostname=snap.inventory.hostname,
        alias="This workstation (live)",
        os=snap.inventory.os,
        kind=MachineKind.local,
        location="Tech bench host",
        owner="Technician",
    )
    _decorate(m, snap)
    if m.snapshot and m.snapshot.telemetry:
        state.telemetry[m.id].append(m.snapshot.telemetry)
    state.machines[m.id] = m
    return m


def seed_demo_fleet() -> list[Machine]:
    created = []
    t = time.time()
    for profile in FLEET:
        state.remediations.pop(profile.id, None)
        state.sim_overrides.pop(profile.id, None)
        snap = snapshot_for(profile.id, t)
        m = Machine(
            id=profile.id,
            hostname=profile.inventory.hostname,
            alias=profile.alias,
            os=profile.inventory.os,
            kind=MachineKind.simulated,
            location=profile.location,
            owner=profile.owner,
        )
        _decorate(m, snap)
        if m.snapshot and m.snapshot.telemetry:
            state.telemetry[m.id].append(m.snapshot.telemetry)
        state.machines[m.id] = m
        created.append(m)
    return created


def list_machines() -> list[Machine]:
    machines = list(state.machines.values())
    rank = {Severity.critical: 0, Severity.warning: 1, Severity.info: 2, Severity.ok: 3}
    machines.sort(key=lambda m: (rank.get(m.overall, 9), m.alias))
    return machines


def get_machine(machine_id: str) -> Machine:
    if machine_id not in state.machines:
        raise KeyError(machine_id)
    return state.machines[machine_id]


def create_pair_code(alias: str, location: str) -> str:
    raw = secrets.token_hex(5).upper()
    code = f"{raw[:5]}-{raw[5:]}"
    state.pair_slots[code] = PairSlot(code=code, alias=alias, location=location, expires=time.time() + 600)
    return code


def register_agent(code: str, inventory) -> tuple[str, Machine]:
    slot = state.pair_slots.get(code.upper())
    if not slot or slot.expires < time.time():
        raise PermissionError("Invalid or expired pairing code")
    del state.pair_slots[code.upper()]
    machine_id = f"remote-{secrets.token_hex(4)}"
    token = secrets.token_urlsafe(24)
    m = Machine(
        id=machine_id,
        hostname=inventory.hostname,
        alias=slot.alias or inventory.hostname,
        os=inventory.os,
        kind=MachineKind.remote,
        location=slot.location or "Remote",
        owner="Paired agent",
        status=MachineStatus.online,
        last_seen=time.time(),
    )
    # Minimal snapshot until the agent posts a full one.
    snap = MachineSnapshot(inventory=inventory)
    _decorate(m, snap, findings=[])
    m.health_score = 100
    m.overall = Severity.info
    state.machines[machine_id] = m
    state.agent_tokens[token] = machine_id
    return token, m


def ingest_agent_snapshot(token: str, snapshot: MachineSnapshot) -> Machine:
    machine_id = state.agent_tokens.get(token)
    if not machine_id:
        raise PermissionError("Bad agent token")
    m = state.machines[machine_id]
    _decorate(m, snapshot)
    if snapshot.telemetry:
        state.telemetry[m.id].append(snapshot.telemetry)
    return m


def ingest_agent_telemetry(token: str, sample: TelemetrySample) -> Machine:
    machine_id = state.agent_tokens.get(token)
    if not machine_id:
        raise PermissionError("Bad agent token")
    m = state.machines[machine_id]
    m.last_seen = time.time()
    m.status = MachineStatus.online
    state.telemetry[m.id].append(sample)
    if m.snapshot:
        m.snapshot.telemetry = sample
    return m


def machine_for_token(token: str) -> Machine:
    machine_id = state.agent_tokens.get(token)
    if not machine_id:
        raise PermissionError("Bad agent token")
    return state.machines[machine_id]


async def run_scan(machine_id: str) -> Machine:
    m = get_machine(machine_id)
    m.status = MachineStatus.scanning
    await state.publish(machine_id, {"type": "machine_update", "machine": m.model_dump(mode="json")})
    for stage, pct, label in SCAN_STAGES:
        await asyncio.sleep(0.28)
        await state.publish(
            machine_id,
            {"type": "scan_progress", "stage": stage, "pct": pct, "label": label},
        )

    if m.kind == MachineKind.local:
        snap = collect_local_snapshot()
    elif m.kind == MachineKind.simulated:
        if machine_id in state.sim_overrides:
            snap = state.sim_overrides[machine_id]
        else:
            snap = snapshot_for(machine_id, time.time())
    else:
        if not m.snapshot:
            raise RuntimeError("Remote machine has not posted a snapshot yet")
        snap = m.snapshot

    _decorate(m, snap)
    if snap.telemetry:
        state.telemetry[m.id].append(snap.telemetry)
    await state.publish(machine_id, {"type": "scan_complete", "machine": m.model_dump(mode="json")})
    return m


def remediate(machine_id: str, finding_id: str) -> Machine:
    m = get_machine(machine_id)
    if not m.snapshot:
        raise RuntimeError("No snapshot")
    state.remediations[machine_id].add(finding_id)
    # Simulated tickets only. Never run OS commands on local or remote PCs.
    if m.kind == MachineKind.simulated:
        snap = apply_remediation(machine_id, finding_id, m.snapshot)
        state.sim_overrides[machine_id] = snap
        _decorate(m, snap)
    else:
        for f in m.findings:
            if f.id == finding_id:
                f.remediated = True
        _score_machine(m)
    return m


def tick_simulated() -> None:
    t = time.time()
    for m in list(state.machines.values()):
        if m.kind != MachineKind.simulated:
            continue
        if m.id in state.sim_overrides:
            snap = state.sim_overrides[m.id]
            # still wobble telemetry a little on a remediated box
            if snap.telemetry:
                sample = snap.telemetry.model_copy()
                sample.ts = t
                state.telemetry[m.id].append(sample)
            continue
        snap = snapshot_for(m.id, t)
        sample = snap.telemetry
        if sample:
            state.telemetry[m.id].append(sample)
            if m.snapshot:
                m.snapshot.telemetry = sample
                # keep component temps in sync for the inspector
                by_id = {c.id: c for c in m.snapshot.components}
                if "cpu" in by_id and sample.cpu_temp_c is not None:
                    by_id["cpu"].metrics["temp_c"] = sample.cpu_temp_c
                if "gpu" in by_id and sample.gpu_temp_c is not None:
                    by_id["gpu"].metrics["temp_c"] = sample.gpu_temp_c
                if "thermal" in by_id and sample.fan_rpm is not None:
                    by_id["thermal"].metrics["fan_rpm"] = sample.fan_rpm


def tick_local() -> None:
    m = state.machines.get("local-workstation")
    if not m:
        return
    sample = collect_local_telemetry()
    state.telemetry[m.id].append(sample)
    if m.snapshot:
        m.snapshot.telemetry = sample
        m.last_seen = time.time()


async def telemetry_loop() -> None:
    while True:
        try:
            tick_simulated()
            tick_local()
            for mid, buf in list(state.telemetry.items()):
                if not buf:
                    continue
                sample = buf[-1]
                await state.publish(
                    mid,
                    {"type": "telemetry", "sample": sample.model_dump(mode="json")},
                )
        except Exception:
            pass
        await asyncio.sleep(1.0)
