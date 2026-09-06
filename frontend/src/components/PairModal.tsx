import { FormEvent, useState } from "react";
import { createPairCode } from "../api";

export default function PairModal({ onClose }: { onClose: () => void }) {
  const [alias, setAlias] = useState("Remote PC");
  const [location, setLocation] = useState("Field");
  const [result, setResult] = useState<{ code: string; agent_command: string } | null>(null);
  const [error, setError] = useState("");

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const data = await createPairCode(alias, location);
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Pairing failed");
    }
  }

  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>Pair a remote PC</h2>
        <p>
          Mint a short-lived code, then run the TECH-BENCH agent on the machine you have
          permission to diagnose. The agent is read-mostly: inventory, health snapshot, and
          telemetry. No reverse shell.
        </p>
        {!result ? (
          <form onSubmit={onSubmit}>
            <label>Alias</label>
            <input value={alias} onChange={(e) => setAlias(e.target.value)} />
            <label>Location</label>
            <input value={location} onChange={(e) => setLocation(e.target.value)} />
            {error && <p className="sev-critical">{error}</p>}
            <div style={{ marginTop: 14, display: "flex", gap: 8 }}>
              <button className="btn btn-amber" type="submit">
                Generate code
              </button>
              <button className="btn" type="button" onClick={onClose}>
                Cancel
              </button>
            </div>
          </form>
        ) : (
          <div>
            <p>Enter this code on the remote agent within 10 minutes:</p>
            <div className="pair-code">{result.code}</div>
            <div className="code-block">{result.agent_command}</div>
            <button className="btn" style={{ marginTop: 12 }} onClick={onClose}>
              Close
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
