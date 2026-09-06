import { useEffect, useState } from "react";

export default function Header({
  machineCount,
  onPair,
}: {
  machineCount: number;
  onPair: () => void;
}) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

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
        <span>{machineCount} bays occupied</span>
        <span>{now.toUTCString().slice(17, 25)} UTC</span>
      </div>
      <div className="header-actions">
        <button className="btn btn-amber" onClick={onPair}>
          Pair remote PC
        </button>
      </div>
    </header>
  );
}
