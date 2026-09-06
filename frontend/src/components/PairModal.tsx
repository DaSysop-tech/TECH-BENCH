import { FormEvent, useState } from "react";
import { agentCommandFor, createPairCode } from "../api";

async function copy(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

export default function PairModal({ onClose }: { onClose: () => void }) {
  const [alias, setAlias] = useState("Remote PC");
  const [locationLabel, setLocationLabel] = useState("Field");
  const [result, setResult] = useState<{ code: string; command: string } | null>(null);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState<"code" | "cmd" | "">("");

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const data = await createPairCode(alias, locationLabel);
      setResult({ code: data.code, command: agentCommandFor(data.code) });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Pairing failed");
    }
  }

  async function onCopy(which: "code" | "cmd", text: string) {
    const ok = await copy(text);
    if (ok) {
      setCopied(which);
      window.setTimeout(() => setCopied(""), 1500);
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
            <input value={locationLabel} onChange={(e) => setLocationLabel(e.target.value)} />
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
            <div className="copy-row">
              <button className="btn" type="button" onClick={() => onCopy("code", result.code)}>
                {copied === "code" ? "Copied" : "Copy code"}
              </button>
            </div>
            <div className="code-block">{result.command}</div>
            <div className="copy-row">
              <button className="btn" type="button" onClick={() => onCopy("cmd", result.command)}>
                {copied === "cmd" ? "Copied" : "Copy command"}
              </button>
            </div>
            <p>
              The command points at this bench ({location.origin}). Remote (non-localhost) benches
              still need HTTPS and a token from <code>data/bench.token</code>.
            </p>
            <button className="btn" style={{ marginTop: 12 }} onClick={onClose}>
              Close
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
