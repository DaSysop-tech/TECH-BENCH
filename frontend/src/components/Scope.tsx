import { Fragment, FormEvent, useEffect, useState } from "react";
import { addNote, downloadText, fetchHistory, fetchReport } from "../api";
import type { BayHistory, ComponentHealth, Finding, Machine, Severity, ToolId } from "../types";

function ringColor(score: number) {
  if (score < 50) return "#ff5a4f";
  if (score < 80) return "#f0c14a";
  return "#3ee08a";
}

function Findings({
  findings,
  filterComponent,
  onRemediate,
  busy,
}: {
  findings: Finding[];
  filterComponent: string | null;
  onRemediate: (id: string) => void;
  busy: boolean;
}) {
  const [sev, setSev] = useState<"all" | Severity>("all");
  const shown = findings.filter((f) => {
    if (filterComponent && f.component !== filterComponent) return false;
    if (sev !== "all" && f.severity !== sev) return false;
    return true;
  });
  return (
    <>
      <div className="rail-filters" style={{ marginBottom: 10 }}>
        {(["all", "critical", "warning", "info"] as const).map((id) => (
          <button
            key={id}
            type="button"
            className={`chip ${sev === id ? "active" : ""}`}
            onClick={() => setSev(id)}
          >
            {id}
          </button>
        ))}
      </div>
      {!shown.length ? (
        <p className="empty">No findings on this subsystem. The bay is clean.</p>
      ) : (
        shown.map((f) => (
          <article key={f.id} className={`finding ${f.remediated ? "remediated" : ""}`}>
            <h4 className={`sev-${f.severity}`}>
              <span className="badge">{f.severity}</span> {f.title}
            </h4>
            <p className="summary">{f.summary}</p>
            {f.evidence.length > 0 && (
              <ul className="ev">
                {f.evidence.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            )}
            {f.recommendations.length > 0 && (
              <ol className="recs">
                {f.recommendations.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ol>
            )}
            <div className="finding-actions">
              <span>confidence {(f.confidence * 100).toFixed(0)}%</span>
              <button
                className="btn"
                disabled={f.remediated || busy}
                onClick={() => onRemediate(f.id)}
              >
                {f.remediated ? "Applied" : "Apply playbook"}
              </button>
            </div>
          </article>
        ))
      )}
    </>
  );
}

function Hardware({ machine }: { machine: Machine }) {
  const inv = machine.snapshot?.inventory;
  if (!inv) return <p className="empty">No inventory yet.</p>;
  return (
    <dl className="kv">
      <dt>Hostname</dt>
      <dd>{inv.hostname}</dd>
      <dt>OS</dt>
      <dd>{inv.os}</dd>
      <dt>CPU</dt>
      <dd>{inv.cpu}</dd>
      <dt>RAM</dt>
      <dd>{inv.ram_gb} GB</dd>
      <dt>GPU</dt>
      <dd>{inv.gpu}</dd>
      <dt>Board</dt>
      <dd>{inv.motherboard}</dd>
      <dt>Disks</dt>
      <dd>{inv.disks.join(", ") || "—"}</dd>
      <dt>IP</dt>
      <dd>{inv.ip || "—"}</dd>
      <dt>Uptime</dt>
      <dd>{inv.uptime_hours.toFixed(1)} h</dd>
    </dl>
  );
}

function Inspector({ component }: { component: ComponentHealth | undefined }) {
  if (!component) return null;
  return (
    <div className="inspector">
      <h4>Probe · {component.label}</h4>
      <dl className="kv">
        <dt>Status</dt>
        <dd className={`sev-${component.status}`}>{component.status}</dd>
        {Object.entries(component.metrics).map(([k, v]) => (
          <Fragment key={k}>
            <dt>{k}</dt>
            <dd>{typeof v === "object" ? JSON.stringify(v) : String(v)}</dd>
          </Fragment>
        ))}
      </dl>
      {component.notes.map((n) => (
        <p key={n} className="empty">
          {n}
        </p>
      ))}
    </div>
  );
}

export default function Scope({
  machine,
  tool,
  selectedComponent,
  onRemediate,
  busy,
}: {
  machine: Machine | null;
  tool: ToolId;
  selectedComponent: string | null;
  onRemediate: (id: string) => void;
  busy: boolean;
}) {
  const [reportState, setReportState] = useState<"idle" | "busy" | "copied" | "error">("idle");
  if (!machine) return <section className="scope" />;
  const snap = machine.snapshot;
  const component = snap?.components.find((c) => c.id === selectedComponent);
  const bayId = machine.id;

  async function onExport(copyOnly: boolean) {
    setReportState("busy");
    try {
      const text = await fetchReport(bayId);
      if (copyOnly) {
        await navigator.clipboard.writeText(text);
        setReportState("copied");
        window.setTimeout(() => setReportState("idle"), 1500);
        return;
      }
      downloadText(`techbench-${bayId}.md`, text);
      setReportState("idle");
    } catch {
      setReportState("error");
    }
  }

  return (
    <section className="scope">
      <div className="panel-label">
        <span>Service tag</span>
        <span className={`sev-${machine.overall}`}>{machine.overall}</span>
      </div>
      <div className="scope-body">
        <div className="gauge-row">
          <div
            className="ring"
            style={{ ["--p" as string]: machine.health_score, ["--ring" as string]: ringColor(machine.health_score) }}
          >
            <span>{machine.health_score}</span>
          </div>
          <div className="meta">
            <p>
              <strong>{machine.alias}</strong>
            </p>
            <p>{machine.hostname}</p>
            <p>{machine.os}</p>
            <p>
              {machine.owner} · {machine.location}
            </p>
            <p>
              {machine.findings.filter((f) => !f.remediated).length} open findings
            </p>
            <div className="copy-row">
              <button className="btn" type="button" disabled={reportState === "busy"} onClick={() => onExport(false)}>
                Export report
              </button>
              <button className="btn" type="button" disabled={reportState === "busy"} onClick={() => onExport(true)}>
                {reportState === "copied" ? "Copied" : "Copy report"}
              </button>
            </div>
            {reportState === "error" && <p className="sev-critical">Could not build report.</p>}
            {machine.last_delta && (
              <p className="delta-banner">
                Last scan {machine.last_delta.score_before}→{machine.last_delta.score_after}
                {" · "}+{machine.last_delta.appeared.length}/−{machine.last_delta.cleared.length}
              </p>
            )}
          </div>
        </div>

        {tool === "findings" || tool === "scan" ? (
          <Findings
            findings={machine.findings}
            filterComponent={selectedComponent}
            onRemediate={onRemediate}
            busy={busy}
          />
        ) : null}

        {tool === "hardware" && <Hardware machine={machine} />}

        {tool === "processes" && (
          <table className="data-table">
            <thead>
              <tr>
                <th>PID</th>
                <th>Name</th>
                <th>CPU</th>
                <th>Mem</th>
                <th>Net</th>
                <th>Signed</th>
              </tr>
            </thead>
            <tbody>
              {(snap?.processes || []).map((p) => (
                <tr key={p.pid}>
                  <td>{p.pid}</td>
                  <td title={p.path}>{p.name}</td>
                  <td>{p.cpu_pct.toFixed(1)}</td>
                  <td>{p.mem_pct.toFixed(1)}</td>
                  <td>{p.net_kbps.toFixed(0)}</td>
                  <td>{p.signed === null ? "—" : p.signed ? "yes" : "NO"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {tool === "network" && (
          <dl className="kv">
            {Object.entries(snap?.network || {}).map(([k, v]) => (
              <Fragment key={k}>
                <dt>{k}</dt>
                <dd>{String(v)}</dd>
              </Fragment>
            ))}
          </dl>
        )}

        {tool === "storage" && (
          <table className="data-table">
            <thead>
              <tr>
                <th>Device</th>
                <th>Health</th>
                <th>Realloc</th>
                <th>Pending</th>
                <th>ms</th>
              </tr>
            </thead>
            <tbody>
              {(snap?.smart || []).map((s) => (
                <tr key={s.device}>
                  <td>
                    {s.model}
                    <br />
                    <span className="empty">{s.device}</span>
                  </td>
                  <td>{s.health}</td>
                  <td>{s.reallocated}</td>
                  <td>{s.pending}</td>
                  <td>{s.latency_ms.toFixed(1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {tool === "thermals" && (
          <dl className="kv">
            <dt>CPU °C</dt>
            <dd>{snap?.telemetry?.cpu_temp_c ?? "n/a"}</dd>
            <dt>GPU °C</dt>
            <dd>{snap?.telemetry?.gpu_temp_c ?? "n/a"}</dd>
            <dt>Fan RPM</dt>
            <dd>{snap?.telemetry?.fan_rpm ?? "n/a"}</dd>
          </dl>
        )}

        {tool === "events" && (
          <ul className="ev">
            {(snap?.events || []).map((e, i) => (
              <li key={i}>
                {e.ts} [{e.level}] {e.source}: {e.message}
              </li>
            ))}
            {(snap?.events || []).length === 0 && <p className="empty">No correlated events.</p>}
          </ul>
        )}

        {tool === "journal" && <JournalPane machineId={machine.id} tool={tool} />}

        <Inspector component={component} />
      </div>
    </section>
  );
}

function JournalPane({
  machineId,
  tool,
}: {
  machineId: string;
  tool: ToolId;
}) {
  const [hist, setHist] = useState<BayHistory | null>(null);
  const [body, setBody] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    fetchHistory(machineId).then(setHist).catch(() => setHist(null));
  }, [machineId, tool]);

  async function onNote(e: FormEvent) {
    e.preventDefault();
    setErr("");
    try {
      await addNote(machineId, body);
      setBody("");
      setHist(await fetchHistory(machineId));
    } catch {
      setErr("Could not save note.");
    }
  }

  if (!hist) return <p className="empty">Loading journal…</p>;
  return (
    <div>
      <h4 className="inspector-h">Scan log</h4>
      {hist.scans.length === 0 && <p className="empty">No scans recorded yet.</p>}
      {hist.scans
        .slice()
        .reverse()
        .map((s) => (
          <p key={s.ts} className="empty">
            score {s.score_before} → {s.score_after} · +{s.appeared.length} / −{s.cleared.length} · open {s.still_open}
          </p>
        ))}
      <h4 className="inspector-h">Journal</h4>
      {hist.journal.length === 0 && <p className="empty">No journal entries yet.</p>}
      <ul className="ev">
        {hist.journal
          .slice()
          .reverse()
          .map((j, i) => (
            <li key={`${j.ts}-${i}`}>
              {j.action} {j.severity ? `[${j.severity}] ` : ""}
              {j.title || j.finding_id}
              {j.detail ? ` — ${j.detail}` : ""}
            </li>
          ))}
      </ul>
      <h4 className="inspector-h">Technician notes</h4>
      {hist.notes.length === 0 && <p className="empty">No notes on this bay.</p>}
      <ul className="ev">
        {hist.notes.map((n) => (
          <li key={n.id}>{n.body}</li>
        ))}
      </ul>
      <form onSubmit={onNote} className="note-form">
        <label htmlFor="note">Add note</label>
        <textarea
          id="note"
          value={body}
          onChange={(e) => setBody(e.target.value)}
          maxLength={2000}
          rows={3}
          required
        />
        {err && <p className="sev-critical">{err}</p>}
        <button className="btn" type="submit">
          Pin note
        </button>
      </form>
    </div>
  );
}
