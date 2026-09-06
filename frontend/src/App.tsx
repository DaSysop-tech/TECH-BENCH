import { useCallback, useEffect, useMemo, useState } from "react";
import Header from "./components/Header";
import LockScreen from "./components/LockScreen";
import MachineRail from "./components/MachineRail";
import PairModal from "./components/PairModal";
import Schematic from "./components/Schematic";
import Scope from "./components/Scope";
import TelemetryStrip from "./components/TelemetryStrip";
import ToolRack from "./components/ToolRack";
import {
  fetchMachine,
  fetchMachines,
  fetchTelemetry,
  openMachineSocket,
  remediate,
  startScan,
  unlockLoopback,
  unlockWithToken,
} from "./api";
import type { Machine, TelemetrySample, ToolId } from "./types";

export default function App() {
  const [unlocked, setUnlocked] = useState(false);
  const [machines, setMachines] = useState<Machine[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [machine, setMachine] = useState<Machine | null>(null);
  const [samples, setSamples] = useState<TelemetrySample[]>([]);
  const [tool, setTool] = useState<ToolId>("findings");
  const [component, setComponent] = useState<string | null>(null);
  const [scanLabel, setScanLabel] = useState<string | null>(null);
  const [pairing, setPairing] = useState(false);
  const [busy, setBusy] = useState(false);

  const refreshList = useCallback(async () => {
    const list = await fetchMachines();
    setMachines(list);
    setSelectedId((cur) => cur ?? list[0]?.id ?? null);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const auto = await unlockLoopback();
      if (cancelled) return;
      if (auto) {
        setUnlocked(true);
        return;
      }
      try {
        await fetchMachines();
        if (!cancelled) setUnlocked(true);
      } catch {
        if (!cancelled) setUnlocked(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!unlocked) return;
    refreshList().catch(console.error);
    const id = setInterval(() => {
      fetchMachines().then(setMachines).catch(() => undefined);
    }, 4000);
    return () => clearInterval(id);
  }, [refreshList, unlocked]);

  useEffect(() => {
    if (!selectedId || !unlocked) return;
    let cancelled = false;
    fetchMachine(selectedId)
      .then((m) => {
        if (!cancelled) setMachine(m);
      })
      .catch(console.error);
    fetchTelemetry(selectedId)
      .then((t) => {
        if (!cancelled) setSamples(t);
      })
      .catch(() => undefined);
    setComponent(null);
    setScanLabel(null);

    const ws = openMachineSocket(selectedId);
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.type === "machine_update" || msg.type === "scan_complete") {
        setMachine(msg.machine);
        setMachines((prev) => prev.map((m) => (m.id === msg.machine.id ? msg.machine : m)));
        if (msg.type === "scan_complete") {
          setScanLabel(null);
          setBusy(false);
        }
      }
      if (msg.type === "scan_progress") {
        setScanLabel(`${msg.pct}% ${msg.label}`);
      }
      if (msg.type === "telemetry") {
        setSamples((prev) => [...prev.slice(-179), msg.sample]);
      }
      if (msg.type === "telemetry_history") {
        setSamples(msg.samples || []);
      }
    };
    return () => {
      cancelled = true;
      ws.close();
    };
  }, [selectedId, unlocked]);

  const components = machine?.snapshot?.components ?? [];

  async function onTool(id: ToolId) {
    setTool(id === "scan" ? "findings" : id);
    if (id === "scan" && selectedId) {
      setBusy(true);
      setScanLabel("Arming probes…");
      try {
        await startScan(selectedId);
      } catch (err) {
        console.error(err);
        setBusy(false);
        setScanLabel(null);
      }
    }
  }

  async function onRemediate(findingId: string) {
    if (!selectedId) return;
    setBusy(true);
    try {
      const next = await remediate(selectedId, findingId);
      setMachine(next);
      setMachines((prev) => prev.map((m) => (m.id === next.id ? next : m)));
    } finally {
      setBusy(false);
    }
  }

  const scanning = machine?.status === "scanning" || Boolean(scanLabel);

  const subtitle = useMemo(() => {
    if (!machine) return "";
    return `${machine.kind} · ${machine.status}`;
  }, [machine]);

  async function handleUnlock(token: string) {
    const ok = await unlockWithToken(token);
    if (ok) setUnlocked(true);
    return ok;
  }

  if (!unlocked) {
    return <LockScreen onUnlock={handleUnlock} />;
  }

  return (
    <div className="app">
      <Header machineCount={machines.length} onPair={() => setPairing(true)} />
      <div className="workspace">
        <MachineRail machines={machines} selectedId={selectedId} onSelect={setSelectedId} />
        <section className="bench">
          <div className="panel-label">
            <span>The bench</span>
            <span>{subtitle}</span>
          </div>
          <div className="bench-body">
            <div className={`mat ${scanning ? "scanning" : ""}`}>
              <Schematic
                components={components}
                selected={component}
                onSelect={(id) => setComponent((cur) => (cur === id ? null : id))}
              />
              {scanLabel && <div className="scan-banner">{scanLabel}</div>}
            </div>
            <ToolRack active={tool} onPick={onTool} />
          </div>
        </section>
        <Scope
          machine={machine}
          tool={tool}
          selectedComponent={component}
          onRemediate={onRemediate}
          busy={busy}
        />
      </div>
      <TelemetryStrip samples={samples} />
      {pairing && (
        <PairModal
          onClose={() => {
            setPairing(false);
            refreshList().catch(() => undefined);
          }}
        />
      )}
    </div>
  );
}
