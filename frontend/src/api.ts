import type { Machine, TelemetrySample } from "./types";

function benchHeaders(json = false): HeadersInit {
  const headers: Record<string, string> = {};
  if (json) headers["Content-Type"] = "application/json";
  const token = localStorage.getItem("techbenchToken") || "";
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

export async function fetchMachines(): Promise<Machine[]> {
  const r = await fetch("/api/machines", { headers: benchHeaders() });
  if (!r.ok) throw new Error("Failed to list machines");
  return r.json();
}

export async function fetchMachine(id: string): Promise<Machine> {
  const r = await fetch(`/api/machines/${id}`, { headers: benchHeaders() });
  if (!r.ok) throw new Error("Machine not found");
  return r.json();
}

export async function fetchTelemetry(id: string): Promise<TelemetrySample[]> {
  const r = await fetch(`/api/machines/${id}/telemetry?limit=180`, { headers: benchHeaders() });
  if (!r.ok) return [];
  return r.json();
}

export async function startScan(id: string): Promise<Machine> {
  const r = await fetch(`/api/machines/${id}/scan`, { method: "POST", headers: benchHeaders() });
  if (!r.ok) throw new Error("Scan failed");
  return r.json();
}

export async function remediate(id: string, findingId: string): Promise<Machine> {
  const r = await fetch(`/api/machines/${id}/remediate`, {
    method: "POST",
    headers: benchHeaders(true),
    body: JSON.stringify({ finding_id: findingId }),
  });
  if (!r.ok) throw new Error("Remediation failed");
  return r.json();
}

export async function createPairCode(alias: string, location: string) {
  const r = await fetch("/api/pair", {
    method: "POST",
    headers: benchHeaders(true),
    body: JSON.stringify({ alias, location }),
  });
  if (!r.ok) throw new Error("Could not mint pairing code");
  return r.json() as Promise<{ code: string; agent_command: string; expires_in_sec: number }>;
}

export function openMachineSocket(id: string): WebSocket {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const token = localStorage.getItem("techbenchToken") || "";
  const q = token ? `?access_token=${encodeURIComponent(token)}` : "";
  return new WebSocket(`${proto}://${location.host}/api/ws/machines/${id}${q}`);
}
