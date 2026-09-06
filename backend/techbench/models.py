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
    id: str
    label: str
    status: Severity
    metrics: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class Finding(BaseModel):
    id: str
    severity: Severity
    component: str
    title: str
    summary: str
    evidence: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    confidence: float = 0.8
    playbook_id: str | None = None
    remediated: bool = False


class ProcessInfo(BaseModel):
    pid: int
    name: str
    cpu_pct: float
    mem_pct: float
    user: str = ""
    signed: bool | None = None
    path: str = ""
    net_kbps: float = 0.0


class VolumeInfo(BaseModel):
    mount: str
    fs: str
    total_gb: float
    used_pct: float
    model: str = ""


class SmartInfo(BaseModel):
    device: str
    model: str
    health: str
    temperature_c: float | None = None
    reallocated: int = 0
    pending: int = 0
    power_on_hours: int = 0
    latency_ms: float = 0.0


class EventInfo(BaseModel):
    ts: str
    source: str
    level: str
    message: str


class TelemetrySample(BaseModel):
    ts: float
    cpu_pct: float
    mem_pct: float
    disk_pct: float
    net_kbps: float
    cpu_temp_c: float | None = None
    gpu_temp_c: float | None = None
    fan_rpm: int | None = None


class Inventory(BaseModel):
    hostname: str
    os: str
    cpu: str
    ram_gb: float
    gpu: str = "Unknown"
    motherboard: str = "Unknown"
    disks: list[str] = Field(default_factory=list, max_length=16)
    uptime_hours: float = 0
    ip: str = ""
    agent_version: str = "1.0.0"


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
    startup_count: int | None = None


class Machine(BaseModel):
    id: str
    hostname: str
    alias: str
    os: str
    kind: MachineKind
    status: MachineStatus = MachineStatus.online
    last_seen: float = 0
    overall: Severity = Severity.ok
    health_score: int = 100
    snapshot: MachineSnapshot | None = None
    findings: list[Finding] = Field(default_factory=list)
    location: str = ""
    owner: str = ""


class PairRequest(BaseModel):
    alias: str = ""
    location: str = ""


class PairResponse(BaseModel):
    code: str
    expires_in_sec: int = 600
    agent_command: str


class AgentRegister(BaseModel):
    code: str
    inventory: Inventory


class AgentSnapshotIn(BaseModel):
    token: str
    snapshot: MachineSnapshot


class AgentTelemetryIn(BaseModel):
    token: str
    sample: TelemetrySample


class RemediateIn(BaseModel):
    finding_id: str


class ScanStage(BaseModel):
    stage: str
    pct: int
    label: str
