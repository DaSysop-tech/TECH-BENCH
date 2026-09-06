import type { Machine } from "../types";

export default function MachineRail({
  machines,
  selectedId,
  onSelect,
}: {
  machines: Machine[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <aside className="rail">
      <div className="panel-label">
        <span>Bays / tickets</span>
        <span>{machines.length}</span>
      </div>
      <div className="machine-list">
        {machines.map((m) => (
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
            </div>
            <div className={`score-chip sev-${m.overall}`}>{m.health_score}</div>
          </button>
        ))}
      </div>
    </aside>
  );
}
