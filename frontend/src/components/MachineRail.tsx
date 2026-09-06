import { useMemo, useState } from "react";
import type { Machine, Severity } from "../types";

type Filter = "all" | Severity;

function relativeSeen(ts: number): string {
  if (!ts) return "never";
  const sec = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (sec < 5) return "just now";
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  return `${Math.floor(min / 60)}h ago`;
}

function matches(machine: Machine, query: string, filter: Filter): boolean {
  if (filter !== "all" && machine.overall !== filter) return false;
  if (!query) return true;
  const hay = `${machine.alias} ${machine.hostname} ${machine.kind} ${machine.location} ${machine.owner}`.toLowerCase();
  return hay.includes(query);
}

export default function MachineRail({
  machines,
  selectedId,
  onSelect,
}: {
  machines: Machine[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const needle = query.trim().toLowerCase();
  const shown = useMemo(
    () => machines.filter((m) => matches(m, needle, filter)),
    [machines, needle, filter],
  );

  return (
    <aside className="rail">
      <div className="panel-label">
        <span>Bays / tickets</span>
        <span>
          {shown.length}/{machines.length}
        </span>
      </div>
      <div className="rail-controls">
        <input
          className="rail-search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search bays"
          aria-label="Search bays"
        />
        <div className="rail-filters">
          {(["all", "critical", "warning", "ok"] as Filter[]).map((id) => (
            <button
              key={id}
              type="button"
              className={`chip ${filter === id ? "active" : ""}`}
              onClick={() => setFilter(id)}
            >
              {id === "all" ? "All" : id}
            </button>
          ))}
        </div>
      </div>
      <div className="machine-list">
        {shown.map((m) => {
          const crit = m.open_critical ?? 0;
          const warn = m.open_warning ?? 0;
          const info = m.open_info ?? 0;
          const open = crit + warn + info;
          return (
            <button
              key={m.id}
              className={`machine-card ${selectedId === m.id ? "active" : ""}`}
              onClick={() => onSelect(m.id)}
            >
              <span className={`led sev-${m.overall}`} />
              <div>
                <h3>{m.alias}</h3>
                <p>
                  {m.hostname} · {m.kind} · {m.location || "unspecified"}
                </p>
                <p className="finding-tally">
                  {open === 0 ? (
                    <span className="sev-ok">clean</span>
                  ) : (
                    <>
                      {crit > 0 && <span className="sev-critical">{crit} crit</span>}
                      {warn > 0 && <span className="sev-warning">{warn} warn</span>}
                      {info > 0 && <span className="sev-info">{info} info</span>}
                    </>
                  )}
                  <span>{relativeSeen(m.last_seen)}</span>
                </p>
              </div>
              <div className={`score-chip sev-${m.overall}`}>{m.health_score}</div>
            </button>
          );
        })}
        {shown.length === 0 && <p className="empty">No bays match that filter.</p>}
      </div>
    </aside>
  );
}
