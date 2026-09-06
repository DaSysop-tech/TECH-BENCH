export type Severity = "ok" | "info" | "warning" | "critical";
export type MachineKind = "local" | "remote" | "simulated";
export type MachineStatus = "online" | "scanning" | "offline";

export interface ComponentHealth {
  id: string;
  label: string;
  status: Severity;
  metrics: Record<string, unknown>;
  notes: string[];
}

export interface Finding {
  id: string;
  severity: Severity;
  component: string;
  title: string;
  summary: string;
  evidence: string[];
  recommendations: string[];
  confidence: number;
  playbook_id: string | null;
  remediated: boolean;
}

export interface ProcessInfo {
  pid: number;
  name: string;
  cpu_pct: number;
  mem_pct: number;
  user: string;
  signed: boolean | null;
  path: string;
  net_kbps: number;
}

export interface VolumeInfo {
  mount: string;
  fs: string;
  total_gb: number;
  used_pct: number;
  model: string;
}

export interface SmartInfo {
  device: string;
  model: string;
  health: string;
  temperature_c: number | null;
  reallocated: number;
  pending: number;
  power_on_hours: number;
  latency_ms: number;
}

export interface EventInfo {
  ts: string;
  source: string;
  level: string;
  message: string;
}

export interface TelemetrySample {
  ts: number;
  cpu_pct: number;
  mem_pct: number;
  disk_pct: number;
  net_kbps: number;
  cpu_temp_c: number | null;
  gpu_temp_c: number | null;
  fan_rpm: number | null;
}

export interface Inventory {
  hostname: string;
  os: string;
  cpu: string;
  ram_gb: number;
  gpu: string;
  motherboard: string;
  disks: string[];
  uptime_hours: number;
  ip: string;
  agent_version: string;
}

export interface MachineSnapshot {
  inventory: Inventory;
  components: ComponentHealth[];
  processes: ProcessInfo[];
  volumes: VolumeInfo[];
  network: Record<string, unknown>;
  events: EventInfo[];
  smart: SmartInfo[];
  telemetry: TelemetrySample | null;
  defender_enabled: boolean | null;
  startup_count: number | null;
}

export interface Machine {
  id: string;
  hostname: string;
  alias: string;
  os: string;
  kind: MachineKind;
  status: MachineStatus;
  last_seen: number;
  overall: Severity;
  health_score: number;
  snapshot?: MachineSnapshot | null;
  findings: Finding[];
  location: string;
  owner: string;
  open_critical?: number;
  open_warning?: number;
  open_info?: number;
  notes?: TechNote[];
  last_delta?: ScanDelta | null;
  cpu_spark?: number[];
  notes_count?: number;
}

export interface TechNote {
  id: string;
  machine_id: string;
  ts: number;
  body: string;
}

export interface JournalEntry {
  machine_id: string;
  ts: number;
  action: string;
  finding_id: string;
  title: string;
  severity: Severity | null;
  detail: string;
}

export interface ScanDelta {
  ts: number;
  score_before: number;
  score_after: number;
  appeared: string[];
  cleared: string[];
  still_open: number;
}

export interface FleetSummary {
  occupied: number;
  critical: number;
  warning: number;
  ok: number;
  offline: number;
  open_critical: number;
  open_warning: number;
  worst: { id: string; alias: string; score: number; overall: Severity } | null;
}

export interface BayHistory {
  journal: JournalEntry[];
  scans: ScanDelta[];
  notes: TechNote[];
}

export type ToolId =
  | "scan"
  | "findings"
  | "hardware"
  | "processes"
  | "network"
  | "storage"
  | "events"
  | "thermals"
  | "journal";
