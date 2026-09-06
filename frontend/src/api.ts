import type { BayHistory, FleetSummary, Machine, TelemetrySample } from "./types";

const CLIENT_HDR = { "X-Techbench": "1" };

function benchHeaders(json = false): HeadersInit {
  const headers: Record<string, string> = { ...CLIENT_HDR };
  if (json) headers["Content-Type"] = "application/json";
  return headers;
}

async function api(path: string, init: RequestInit = {}): Promise<Response> {
  return fetch(path, { credentials: "include", ...init, headers: { ...benchHeaders(), ...(init.headers || {}) } });
}

export async function unlockLoopback(): Promise<boolean> {
  const r = await api("/api/session/loopback", { method: "POST" });
  return r.ok;
}

export async function unlockWithToken(token: string): Promise<boolean> {
  const r = await api("/api/session", {
    method: "POST",
    headers: benchHeaders(true),
    body: JSON.stringify({ token }),
  });
  return r.ok;
}

export async function fetchMachines(): Promise<Machine[]> {
  const r = await api("/api/machines");
  if (r.status === 401) {
    const err = new Error("unauthorized");
    (err as Error & { status: number }).status = 401;
    throw err;
  }
  if (!r.ok) throw new Error("Failed to list machines");
  return r.json();
}

export async function fetchMachine(id: string): Promise<Machine> {
  const r = await api(`/api/machines/${id}`);
  if (!r.ok) throw new Error("Machine not found");
  return r.json();
}

export async function fetchTelemetry(id: string): Promise<TelemetrySample[]> {
  const r = await api(`/api/machines/${id}/telemetry?limit=180`);
  if (!r.ok) return [];
  return r.json();
}

export async function fetchReport(id: string): Promise<string> {
  const r = await api(`/api/machines/${id}/report`);
  if (!r.ok) throw new Error("Report failed");
  return r.text();
}

export function downloadText(filename: string, text: string) {
  const blob = new Blob([text], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export async function startScan(id: string): Promise<Machine> {
  const r = await api(`/api/machines/${id}/scan`, { method: "POST" });
  if (!r.ok) throw new Error("Scan failed");
  return r.json();
}

export async function remediate(id: string, findingId: string): Promise<Machine> {
  const r = await api(`/api/machines/${id}/remediate`, {
    method: "POST",
    headers: benchHeaders(true),
    body: JSON.stringify({ finding_id: findingId }),
  });
  if (!r.ok) throw new Error("Remediation failed");
  return r.json();
}

export async function createPairCode(alias: string, location: string) {
  const r = await api("/api/pair", {
    method: "POST",
    headers: benchHeaders(true),
    body: JSON.stringify({ alias, location }),
  });
  if (!r.ok) throw new Error("Could not mint pairing code");
  return r.json() as Promise<{ code: string; agent_command: string; expires_in_sec: number }>;
}

export function agentCommandFor(code: string): string {
  const loopback = ["localhost", "127.0.0.1"].includes(location.hostname);
  const tokenArg = loopback ? '"$(cat data/bench.token)"' : "BENCH_TOKEN";
  return `python agent/techbench_agent.py --server ${location.origin} --code ${code} --bench-token ${tokenArg}`;
}

export function openMachineSocket(id: string): WebSocket {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return new WebSocket(`${proto}://${location.host}/api/ws/machines/${id}`);
}

export function openFleetSocket(): WebSocket {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return new WebSocket(`${proto}://${location.host}/api/ws/fleet`);
}

export async function fetchFleet(): Promise<FleetSummary> {
  const r = await api("/api/fleet");
  if (!r.ok) throw new Error("Fleet failed");
  return r.json();
}

export async function fetchNextTicket(after?: string | null): Promise<Machine> {
  const q = after ? `?after=${encodeURIComponent(after)}` : "";
  const r = await api(`/api/fleet/next${q}`);
  if (!r.ok) throw new Error("No next ticket");
  return r.json();
}

export async function fetchHistory(id: string): Promise<BayHistory> {
  const r = await api(`/api/machines/${id}/history`);
  if (!r.ok) throw new Error("History failed");
  return r.json();
}

export async function addNote(id: string, body: string) {
  const r = await api(`/api/machines/${id}/notes`, {
    method: "POST",
    headers: benchHeaders(true),
    body: JSON.stringify({ body }),
  });
  if (!r.ok) throw new Error("Note failed");
  return r.json();
}
