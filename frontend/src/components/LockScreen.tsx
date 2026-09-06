import { FormEvent, useState } from "react";

export default function LockScreen({ onUnlock }: { onUnlock: (token: string) => Promise<boolean> }) {
  const [token, setToken] = useState("");
  const [error, setError] = useState("");

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    const ok = await onUnlock(token);
    if (!ok) setError("That token was rejected.");
  }

  return (
    <div className="modal-back">
      <div className="modal">
        <h2>Bench lock</h2>
        <p>
          This console is locked. On the machine running TECH-BENCH, the browser at 127.0.0.1
          unlocks by itself. From anywhere else, paste the token from <code>data/bench.token</code>.
        </p>
        <form onSubmit={onSubmit}>
          <label>Bench token</label>
          <input value={token} onChange={(e) => setToken(e.target.value)} autoComplete="off" />
          {error && <p className="sev-critical">{error}</p>}
          <div style={{ marginTop: 14 }}>
            <button className="btn btn-amber" type="submit">
              Unlock
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}