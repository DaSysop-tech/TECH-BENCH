import type { ComponentHealth, Severity } from "../types";

const FILL: Record<Severity, string> = {
  ok: "#1d3d32",
  info: "#1b3348",
  warning: "#4a3a14",
  critical: "#4a1b18",
};

const STROKE: Record<Severity, string> = {
  ok: "#3ee08a",
  info: "#5cb0ff",
  warning: "#f0c14a",
  critical: "#ff5a4f",
};

function statusOf(components: ComponentHealth[], id: string): Severity {
  return components.find((c) => c.id === id)?.status ?? "ok";
}

export default function Schematic({
  components,
  selected,
  onSelect,
}: {
  components: ComponentHealth[];
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const cpu = statusOf(components, "cpu");
  const mem = statusOf(components, "memory");
  const storage = statusOf(components, "storage");
  const gpu = statusOf(components, "gpu");
  const net = statusOf(components, "network");
  const psu = statusOf(components, "psu");
  const thermal = statusOf(components, "thermal");
  const os = statusOf(components, "os");

  return (
    <svg className="schematic" viewBox="0 0 900 560" role="img" aria-label="PC schematic">
      <defs>
        <filter id="glow">
          <feGaussianBlur stdDeviation="2.2" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
        <linearGradient id="pcb" x1="0" x2="1">
          <stop offset="0%" stopColor="#12352c" />
          <stop offset="100%" stopColor="#0c241e" />
        </linearGradient>
      </defs>

      <rect x="40" y="28" width="820" height="504" rx="10" fill="#151820" stroke="#3a4254" />
      <rect x="58" y="46" width="784" height="430" rx="8" fill="url(#pcb)" stroke="#2d6b55" />

      <text x="70" y="38" fill="#8b93a4" fontSize="11" fontFamily="IBM Plex Mono">
        CHASSIS / ATX · click a subsystem
      </text>

      {/* Rear I/O / network */}
      <g
        className={`part ${selected === "network" ? "selected" : ""}`}
        onClick={() => onSelect("network")}
        filter="url(#glow)"
      >
        <rect x="70" y="62" width="170" height="52" fill={FILL[net]} stroke={STROKE[net]} />
        <text x="82" y="82" fill="#e7e4d8" fontSize="12">
          REAR I/O
        </text>
        <text x="82" y="100" fill={STROKE[net]} fontSize="11" fontFamily="IBM Plex Mono">
          NIC / LAN
        </text>
      </g>

      {/* PSU */}
      <g
        className={`part ${selected === "psu" ? "selected" : ""}`}
        onClick={() => onSelect("psu")}
        filter="url(#glow)"
      >
        <rect x="680" y="62" width="146" height="86" fill={FILL[psu]} stroke={STROKE[psu]} />
        <text x="696" y="88" fill="#e7e4d8" fontSize="13">
          PSU
        </text>
        <text x="696" y="108" fill={STROKE[psu]} fontSize="11" fontFamily="IBM Plex Mono">
          ATX rails
        </text>
      </g>

      {/* CPU */}
      <g
        className={`part ${selected === "cpu" ? "selected" : ""}`}
        onClick={() => onSelect("cpu")}
        filter="url(#glow)"
      >
        <rect x="160" y="150" width="150" height="120" fill={FILL[cpu]} stroke={STROKE[cpu]} />
        <rect x="178" y="168" width="114" height="84" fill="#0d1118" stroke={STROKE[cpu]} />
        <text x="190" y="216" fill={STROKE[cpu]} fontSize="16" fontFamily="Chakra Petch">
          CPU
        </text>
      </g>

      {/* Memory DIMMs */}
      <g
        className={`part ${selected === "memory" ? "selected" : ""}`}
        onClick={() => onSelect("memory")}
        filter="url(#glow)"
      >
        {[0, 1, 2, 3].map((i) => (
          <rect
            key={i}
            x={340}
            y={150 + i * 28}
            width="150"
            height="22"
            fill={FILL[mem]}
            stroke={STROKE[mem]}
          />
        ))}
        <text x="350" y="142" fill="#e7e4d8" fontSize="11">
          DIMM / MEMORY
        </text>
      </g>

      {/* Chipset / OS */}
      <g
        className={`part ${selected === "os" ? "selected" : ""}`}
        onClick={() => onSelect("os")}
        filter="url(#glow)"
      >
        <rect x="160" y="290" width="90" height="48" fill={FILL[os]} stroke={STROKE[os]} />
        <text x="172" y="320" fill="#e7e4d8" fontSize="12">
          PCH / OS
        </text>
      </g>

      {/* GPU */}
      <g
        className={`part ${selected === "gpu" ? "selected" : ""}`}
        onClick={() => onSelect("gpu")}
        filter="url(#glow)"
      >
        <rect x="160" y="360" width="430" height="70" fill={FILL[gpu]} stroke={STROKE[gpu]} />
        <text x="176" y="402" fill="#e7e4d8" fontSize="16" fontFamily="Chakra Petch">
          GPU / PCIe x16
        </text>
      </g>

      {/* Storage */}
      <g
        className={`part ${selected === "storage" ? "selected" : ""}`}
        onClick={() => onSelect("storage")}
        filter="url(#glow)"
      >
        <rect x="540" y="150" width="180" height="46" fill={FILL[storage]} stroke={STROKE[storage]} />
        <text x="552" y="178" fill="#e7e4d8" fontSize="12">
          M.2 NVMe
        </text>
        <rect x="540" y="208" width="180" height="70" fill={FILL[storage]} stroke={STROKE[storage]} />
        <text x="552" y="248" fill="#e7e4d8" fontSize="12">
          SATA / HDD
        </text>
      </g>

      {/* Fans / thermal */}
      <g
        className={`part ${selected === "thermal" ? "selected" : ""}`}
        onClick={() => onSelect("thermal")}
        filter="url(#glow)"
      >
        <circle cx="120" cy="430" r="32" fill={FILL[thermal]} stroke={STROKE[thermal]} />
        <circle cx="760" cy="430" r="32" fill={FILL[thermal]} stroke={STROKE[thermal]} />
        <text x="98" y="478" fill="#e7e4d8" fontSize="11">
          FANS
        </text>
      </g>
    </svg>
  );
}
