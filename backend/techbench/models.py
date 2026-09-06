from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Severity(str, Enum):
    ok = "ok"
    info = "info"
    warning = "warning"
    critical = "critical"


class MachineKind(str, Enum):
    local = "local"
    remote = "remote"
    simulated = "simulated"


class MachineStatus(str, Enum):
    online = "online"
    scanning = "scanning"
    offline = "offline"


class ComponentHealth(BaseModel):
    id: str = Field(max_length=64)
    label: str = Field(max_length=64)
    status: Severity
    metrics: dict[str, Any] = Field(default_factory=dict, max_length=24)
    notes: list[str] = Field(default_factory=list, max_length=16)


class Finding(BaseModel):
    id: str = Field(max_length=96)
    severity: Severity
    component: str = Field(max_length=32)
    title: str = Field(max_length=200)
    summary: str = Field(max_length=2000)
    evidence: list[str] = Field(default_factory=list, max_length=12)
    recommendations: list[str] = Field(default_factory=list, max_length=12)
    confidence: float = Field(default=0.8, ge=0, le=1)
    playbook_id: str | None = Field(default=None, max_length=64)
    remediated: bool = False


class ProcessInfo(BaseModel):
    pid: int = Field(ge=0, le=4_000_000_000)
    name: str = Field(max_length=128)
    cpu_pct: float = Field(ge=0, le=100)
    mem_pct: float = Field(ge=0, le=100)
    user: str = Field(default="", max_length=64)
    signed: bool | None = None
    path: str = Field(default="", max_length=180)
    net_kbps: float = Field(default=0.0, ge=0, le=10_000_000)


class VolumeInfo(BaseModel):
    mount: str = Field(max_length=64)
    fs: str = Field(max_length=32)
    total_gb: float = Field(ge=0, le=1_000_000)
    used_pct: float = Field(ge=0, le=100)
    model: str = Field(default="", max_length=128)


class SmartInfo(BaseModel):
    device: str = Field(max_length=64)
    model: str = Field(max_length=128)
    health: str = Field(max_length=64)
    temperature_c: float | None = Field(default=None, ge=-50, le=200)
    reallocated: int = Field(default=0, ge=0, le=1_000_000)
    pending: int = Field(default=0, ge=0, le=1_000_000)
    power_on_hours: int = Field(default=0, ge=0, le=1_000_000)
    latency_ms: float = Field(default=0.0, ge=0, le=60_000)


class EventInfo(BaseModel):
    ts: str = Field(max_length=64)
    source: str = Field(max_length=128)
    level: str = Field(max_length=32)
    message: str = Field(max_length=500)


class TelemetrySample(BaseModel):
    ts: float
    cpu_pct: float = Field(ge=0, le=100)
    mem_pct: float = Field(ge=0, le=100)
    disk_pct: float = Field(ge=0, le=100)
    net_kbps: float = Field(ge=0, le=10_000_000)
    cpu_temp_c: float | None = Field(default=None, ge=-50, le=200)
    gpu_temp_c: float | None = Field(default=None, ge=-50, le=200)
    fan_rpm: int | None = Field(default=None, ge=0, le=50_000)


class Inventory(BaseModel):
    hostname: str = Field(max_length=128)
    os: str = Field(max_length=128)
    cpu: str = Field(max_length=128)
    ram_gb: float = Field(ge=0, le=4096)
    gpu: str = Field(default="Unknown", max_length=128)
    motherboard: str = Field(default="Unknown", max_length=128)
    disks: list[str] = Field(default_factory=list, max_length=16)
    uptime_hours: float = Field(default=0, ge=0, le=1_000_000)
    ip: str = Field(default="", max_length=64)
    agent_version: str = Field(default="1.0.0", max_length=32)


class MachineSnapshot(BaseModel):
    inventory: Inventory
    components: list[ComponentHealth] = Field(default_factory=list, max_length=32)
    processes: list[ProcessInfo] = Field(default_factory=list, max_length=64)
    volumes: list[VolumeInfo] = Field(default_factory=list, max_length=32)
    network: dict[str, Any] = Field(default_factory=dict, max_length=32)
    events: list[EventInfo] = Field(default_factory=list, max_length=50)
    smart: list[SmartInfo] = Field(default_factory=list, max_length=16)
    telemetry: TelemetrySample | None = None
    defender_enabled: bool | None = None
    startup_count: int | None = Field(default=None, ge=0, le=10_000)


class Machine(BaseModel):
    id: str = Field(max_length=64)
    hostname: str = Field(max_length=128)
    alias: str = Field(max_length=128)
    os: str = Field(max_length=128)
    kind: MachineKind
    status: MachineStatus = MachineStatus.online
    last_seen: float = 0
    overall: Severity = Severity.ok
    health_score: int = Field(default=100, ge=0, le=100)
    snapshot: MachineSnapshot | None = None
    findings: list[Finding] = Field(default_factory=list, max_length=40)
    location: str = Field(default="", max_length=128)
    owner: str = Field(default="", max_length=128)


class PairRequest(BaseModel):
    alias: str = Field(default="", max_length=64)
    location: str = Field(default="", max_length=64)


class PairResponse(BaseModel):
    code: str
    expires_in_sec: int = 600
    agent_command: str


class AgentRegister(BaseModel):
    code: str = Field(max_length=24)
    inventory: Inventory


class AgentSnapshotIn(BaseModel):
    token: str = Field(max_length=128)
    snapshot: MachineSnapshot


class AgentTelemetryIn(BaseModel):
    token: str = Field(max_length=128)
    sample: TelemetrySample


class RemediateIn(BaseModel):
    finding_id: str = Field(max_length=96)


class SessionIn(BaseModel):
    token: str = Field(max_length=200)


class ScanStage(BaseModel):
    stage: str
    pct: int
    label: str
