import { useEffect, useRef } from "react";
import type { TelemetrySample } from "../types";

function draw(
  canvas: HTMLCanvasElement,
  values: number[],
  color: string,
  maxHint?: number,
) {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  canvas.width = Math.max(1, Math.floor(w * dpr));
  canvas.height = Math.max(1, Math.floor(h * dpr));
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  ctx.strokeStyle = "#1c2433";
  ctx.lineWidth = 1;
  for (let i = 0; i < 4; i++) {
    const y = (h / 4) * i;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
    ctx.stroke();
  }
  if (values.length < 2) return;
  const max = Math.max(maxHint ?? 100, ...values, 1);
  ctx.beginPath();
  values.forEach((v, i) => {
    const x = (i / (values.length - 1)) * w;
    const y = h - (Math.min(v, max) / max) * (h - 4) - 2;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.6;
  ctx.stroke();
}

function Channel({
  label,
  unit,
  color,
  values,
  current,
  maxHint,
}: {
  label: string;
  unit: string;
  color: string;
  values: number[];
  current: number;
  maxHint?: number;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    if (ref.current) draw(ref.current, values, color, maxHint);
  }, [values, color, maxHint]);
  return (
    <div className="channel">
      <header>
        <span>{label}</span>
        <span>
          {current.toFixed(0)}
          {unit}
        </span>
      </header>
      <canvas ref={ref} />
    </div>
  );
}

export default function TelemetryStrip({ samples }: { samples: TelemetrySample[] }) {
  const last = samples[samples.length - 1];
  return (
    <footer className="telemetry">
      <div className="telemetry-label">
        <div>SCOPE</div>
        <div style={{ color: "#8b93a4", letterSpacing: "0.08em" }}>1 Hz live</div>
      </div>
      <div className="channels">
        <Channel
          label="CPU"
          unit="%"
          color="#e8a33a"
          values={samples.map((s) => s.cpu_pct)}
          current={last?.cpu_pct ?? 0}
        />
        <Channel
          label="RAM"
          unit="%"
          color="#5cb0ff"
          values={samples.map((s) => s.mem_pct)}
          current={last?.mem_pct ?? 0}
        />
        <Channel
          label="TEMP"
          unit="°"
          color="#ff5a4f"
          values={samples.map((s) => s.cpu_temp_c ?? 0)}
          current={last?.cpu_temp_c ?? 0}
          maxHint={110}
        />
        <Channel
          label="NET"
          unit="k"
          color="#3ee08a"
          values={samples.map((s) => s.net_kbps)}
          current={last?.net_kbps ?? 0}
          maxHint={Math.max(800, ...samples.map((s) => s.net_kbps), 1)}
        />
      </div>
    </footer>
  );
}
