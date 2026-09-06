import type { ToolId } from "../types";

const TOOLS: { id: ToolId; label: string }[] = [
  { id: "scan", label: "Full scan" },
  { id: "findings", label: "Findings" },
  { id: "hardware", label: "Hardware" },
  { id: "processes", label: "Processes" },
  { id: "network", label: "Network" },
  { id: "storage", label: "SMART" },
  { id: "thermals", label: "Thermal" },
  { id: "events", label: "Event log" },
];

export default function ToolRack({
  active,
  onPick,
}: {
  active: ToolId;
  onPick: (id: ToolId) => void;
}) {
  return (
    <div className="tools">
      {TOOLS.map((t) => (
        <button
          key={t.id}
          className={`tool ${active === t.id ? "active" : ""}`}
          onClick={() => onPick(t.id)}
        >
          <div className="dot" />
          {t.label}
        </button>
      ))}
    </div>
  );
}
