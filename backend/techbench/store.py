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
    JournalEntry,
    Machine,
    MachineKind,
    MachineSnapshot,
    MachineStatus,
    ScanDelta,
    Severity,
    TechNote,
    TelemetrySample,
)
from techbench.persist import (
    clear_sim_ticket,
    init_db,
    load_all,
    save_journal,
    save_note,
    save_override,
    save_remediation,
    save_remote,
    save_scan,
    save_telemetry,
    save_token,
)
from techbench.sim.fleet import FLEET, apply_remediation, snapshot_for


FLEET_CHANNEL = "__fleet__"
REMOTE_OFFLINE_SEC = 90

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
    journal: dict[str, deque] = field(default_factory=lambda: defaultdict(lambda: deque(maxlen=80)))
    scans: dict[str, deque] = field(default_factory=lambda: defaultdict(lambda: deque(maxlen=20)))
    last_overall: dict[str, Severity] = field(default_factory=dict)

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


def _append_journal(entry: JournalEntry) -> None:
    state.journal[entry.machine_id].append(entry)
    save_journal(entry)


def _emit_fleet(payload: dict) -> None:
    dead = []
    for q in list(state.subscribers.get(FLEET_CHANNEL, ())):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        state.subscribers[FLEET_CHANNEL].discard(q)


def _score_machine(machine: Machine) -> None:
    prev = state.last_overall.get(machine.id)
    machine.overall = overall_severity(machine.findings)
    machine.health_score = health_score(machine.findings)
    active = [f for f in machine.findings if not f.remediated]
    machine.open_critical = sum(1 for f in active if f.severity == Severity.critical)
    machine.open_warning = sum(1 for f in active if f.severity == Severity.warning)
    machine.open_info = sum(1 for f in active if f.severity == Severity.info)
    machine.notes_count = len(machine.notes)
    buf = state.telemetry.get(machine.id, ())
    machine.cpu_spark = [round(s.cpu_pct, 1) for s in list(buf)[-24:]]
    state.last_overall[machine.id] = machine.overall
    if prev is not None and prev != machine.overall:
        _emit_fleet(
            {
                "type": "fleet_alert",
                "machine_id": machine.id,
                "alias": machine.alias,
                "from": prev.value,
                "to": machine.overall.value,
                "score": machine.health_score,
            }
        )


def _decorate(machine: Machine, snapshot: MachineSnapshot, findings: list[Finding] | None = None, *, journal: bool = True) -> Machine:
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
    if journal and machine.id in state.machines:
        old_map = {f.id: f for f in machine.findings}
        new_ids = {f.id for f in findings}
        for fid, old in old_map.items():
            if fid not in new_ids and not old.remediated:
                _append_journal(
                    JournalEntry(
                        machine_id=machine.id,
                        ts=time.time(),
                        action="cleared",
                        finding_id=fid,
                        title=old.title,
                        severity=old.severity,
                    )
                )
        for f in findings:
            if f.id not in old_map:
                _append_journal(
                    JournalEntry(
                        machine_id=machine.id,
                        ts=time.time(),
                        action="appeared",
                        finding_id=f.id,
                        title=f.title,
                        severity=f.severity,
                    )
                )
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
    _decorate(m, snap, journal=False)
    if m.snapshot and m.snapshot.telemetry:
        state.telemetry[m.id].append(m.snapshot.telemetry)
        m.cpu_spark = [m.snapshot.telemetry.cpu_pct]
    state.machines[m.id] = m
    return m


def seed_demo_fleet(*, reset: bool = True) -> list[Machine]:
    created = []
    t = time.time()
    for profile in FLEET:
        if reset:
            state.remediations.pop(profile.id, None)
            state.sim_overrides.pop(profile.id, None)
            clear_sim_ticket(profile.id)
        snap = state.sim_overrides.get(profile.id)
        if snap is None:
            snap = snapshot_for(profile.id, t)
            if not reset and profile.id in state.remediations:
                for fid in list(state.remediations[profile.id]):
                    snap = apply_remediation(profile.id, fid, snap)
                state.sim_overrides[profile.id] = snap
                save_override(profile.id, snap)
        m = Machine(
            id=profile.id,
            hostname=profile.inventory.hostname,
            alias=profile.alias,
            os=profile.inventory.os,
            kind=MachineKind.simulated,
            location=profile.location,
            owner=profile.owner,
        )
        _decorate(m, snap, journal=False)
        if m.snapshot and m.snapshot.telemetry:
            state.telemetry[m.id].append(m.snapshot.telemetry)
        state.machines[m.id] = m
        created.append(m)
    return created


def list_machines() -> list[Machine]:
    machines = list(state.machines.values())
    rank = {Severity.critical: 0, Severity.warning: 1, Severity.info: 2, Severity.ok: 3}
    machines.sort(key=lambda m: (rank.get(m.overall, 9), m.health_score, m.alias))
    return machines


def machine_card(machine: Machine) -> dict:
    _score_machine(machine)
    return machine.model_dump(mode="json", exclude={"snapshot", "notes"})


def boot_bench() -> None:
    init_db()
    blob = load_all()
    state.remediations = defaultdict(set, {k: set(v) for k, v in blob["remediations"].items()})
    state.sim_overrides = dict(blob["overrides"])
    state.agent_tokens = dict(blob["tokens"])
    state.journal = defaultdict(lambda: deque(maxlen=80), blob["journal"])
    state.scans = defaultdict(lambda: deque(maxlen=20), blob["scans"])
    seed_local()
    seed_demo_fleet(reset=False)
    for remote in blob["remotes"]:
        if remote.id in state.machines:
            continue
        if time.time() - remote.last_seen > REMOTE_OFFLINE_SEC:
            remote.status = MachineStatus.offline
        state.machines[remote.id] = remote
        state.last_overall[remote.id] = remote.overall
    for mid, samples in blob["telemetry"].items():
        if mid in state.machines:
            state.telemetry[mid].extend(samples)
    for mid, notes in blob["notes"].items():
        if mid in state.machines:
            state.machines[mid].notes = notes
            state.machines[mid].notes_count = len(notes)


def fleet_summary() -> dict:
    machines = list_machines()
    crit = [m for m in machines if m.overall == Severity.critical]
    warn = [m for m in machines if m.overall == Severity.warning]
    ok = [m for m in machines if m.overall in {Severity.ok, Severity.info}]
    offline = [m for m in machines if m.status == MachineStatus.offline]
    worst = machines[0] if machines else None
    return {
        "occupied": len(machines),
        "critical": len(crit),
        "warning": len(warn),
        "ok": len(ok),
        "offline": len(offline),
        "open_critical": sum(m.open_critical for m in machines),
        "open_warning": sum(m.open_warning for m in machines),
        "worst": (
            {
                "id": worst.id,
                "alias": worst.alias,
                "score": worst.health_score,
                "overall": worst.overall.value,
            }
            if worst
            else None
        ),
    }


def next_ticket(after_id: str | None = None) -> Machine | None:
    ranked = list_machines()
    if not ranked:
        return None
    if not after_id:
        return ranked[0]
    ids = [m.id for m in ranked]
    if after_id in ids:
        return ranked[(ids.index(after_id) + 1) % len(ranked)]
    return ranked[0]


def machine_history(machine_id: str) -> dict:
    get_machine(machine_id)
    return {
        "journal": [e.model_dump(mode="json") for e in list(state.journal.get(machine_id, ()))[-40:]],
        "scans": [s.model_dump(mode="json") for s in list(state.scans.get(machine_id, ()))[-12:]],
        "notes": [n.model_dump(mode="json") for n in get_machine(machine_id).notes],
    }


def add_note(machine_id: str, body: str) -> TechNote:
    m = get_machine(machine_id)
    note = TechNote(
        id=secrets.token_hex(8),
        machine_id=machine_id,
        ts=time.time(),
        body=body.strip(),
    )
    m.notes.append(note)
    m.notes = m.notes[-40:]
    m.notes_count = len(m.notes)
    save_note(note)
    _append_journal(
        JournalEntry(
            machine_id=machine_id,
            ts=note.ts,
            action="note",
            title="Technician note",
            detail=body.strip()[:400],
        )
    )
    return note


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
    _decorate(m, snap, findings=[], journal=False)
    m.health_score = 100
    m.overall = Severity.info
    state.machines[machine_id] = m
    state.agent_tokens[token] = machine_id
    save_token(token, machine_id)
    save_remote(m)
    return token, m


def ingest_agent_snapshot(token: str, snapshot: MachineSnapshot) -> Machine:
    machine_id = state.agent_tokens.get(token)
    if not machine_id:
        raise PermissionError("Bad agent token")
    m = state.machines[machine_id]
    _decorate(m, snapshot)
    if snapshot.telemetry:
        state.telemetry[m.id].append(snapshot.telemetry)
    save_remote(m)
    save_telemetry(m.id, list(state.telemetry[m.id]))
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
    before = m.health_score
    before_ids = {f.id for f in m.findings if not f.remediated}
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
    after_ids = {f.id for f in m.findings if not f.remediated}
    delta = ScanDelta(
        ts=time.time(),
        score_before=before,
        score_after=m.health_score,
        appeared=sorted(after_ids - before_ids),
        cleared=sorted(before_ids - after_ids),
        still_open=len(after_ids),
    )
    m.last_delta = delta
    state.scans[machine_id].append(delta)
    save_scan(machine_id, delta)
    await state.publish(
        machine_id,
        {"type": "scan_complete", "machine": m.model_dump(mode="json"), "delta": delta.model_dump(mode="json")},
    )
    return m


def remediate(machine_id: str, finding_id: str) -> Machine:
    m = get_machine(machine_id)
    if not m.snapshot:
        raise RuntimeError("No snapshot")
    titled = next((f.title for f in m.findings if f.id == finding_id), finding_id)
    sev = next((f.severity for f in m.findings if f.id == finding_id), None)
    state.remediations[machine_id].add(finding_id)
    save_remediation(machine_id, finding_id)
    # Simulated tickets only. Never run OS commands on local or remote PCs.
    if m.kind == MachineKind.simulated:
        snap = apply_remediation(machine_id, finding_id, m.snapshot)
        state.sim_overrides[machine_id] = snap
        save_override(machine_id, snap)
        _decorate(m, snap)
    else:
        for f in m.findings:
            if f.id == finding_id:
                f.remediated = True
        _score_machine(m)
    _append_journal(
        JournalEntry(
            machine_id=machine_id,
            ts=time.time(),
            action="remediated",
            finding_id=finding_id,
            title=titled,
            severity=sev,
        )
    )
    return m


def tick_simulated() -> None:
    t = time.time()
    for m in list(state.machines.values()):
        if m.kind != MachineKind.simulated:
            continue
        if m.id in state.sim_overrides:
            snap = state.sim_overrides[m.id]
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


def tick_remote_offline() -> None:
    now = time.time()
    for m in list(state.machines.values()):
        if m.kind != MachineKind.remote:
            continue
        if now - m.last_seen > REMOTE_OFFLINE_SEC and m.status != MachineStatus.scanning:
            m.status = MachineStatus.offline


async def telemetry_loop() -> None:
    ticks = 0
    while True:
        try:
            tick_simulated()
            tick_local()
            tick_remote_offline()
            ticks += 1
            for mid, buf in list(state.telemetry.items()):
                if not buf:
                    continue
                sample = buf[-1]
                await state.publish(
                    mid,
                    {"type": "telemetry", "sample": sample.model_dump(mode="json")},
                )
            if ticks % 15 == 0:
                for m in list(state.machines.values()):
                    if m.kind == MachineKind.remote:
                        save_telemetry(m.id, list(state.telemetry.get(m.id, ())))
                        save_remote(m)
        except Exception:
            pass
        await asyncio.sleep(1.0)
