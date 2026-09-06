import { useEffect, useState } from "react";
import type { FleetSummary } from "../types";

export default function Header({
  summary,
  onPair,
  onNext,
  onHelp,
}: {
  summary: FleetSummary | null;
  onPair: () => void;
  onNext: () => void;
  onHelp: () => void;
}) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  const worst = summary?.worst;

  return (
    <header className="header">
      <div className="brand">
        <div className="brand-mark">TB</div>
        <div>
          <h1>TECH-BENCH</h1>
          <p>Virtual diagnostic workstation</p>
        </div>
      </div>
      <div className="header-status">
        <div className="live-pill">
          <span className="led" />
          LIVE
        </div>
        <span>{summary ? `${summary.occupied} bays` : "—"}</span>
        {summary && (
          <span>
            <span className="sev-critical">{summary.critical} crit</span>
            {" · "}
            <span className="sev-warning">{summary.warning} warn</span>
            {summary.offline > 0 ? ` · ${summary.offline} offline` : ""}
          </span>
        )}
        <span>{now.toUTCString().slice(17, 25)} UTC</span>
      </div>
      <div className="header-actions">
        {worst && (
          <button className="btn" type="button" onClick={onNext} title="Next ticket (n)">
            Next · {worst.alias} {worst.score}
          </button>
        )}
        <button className="btn" type="button" onClick={onHelp} title="Keyboard shortcuts (?)">
          Keys
        </button>
        <button className="btn btn-amber" onClick={onPair}>
          Pair remote PC
        </button>
      </div>
    </header>
  );
}
