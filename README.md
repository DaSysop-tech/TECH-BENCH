# TECH-BENCH

A **local technician workstation**. Pair (with consent) to a PC, pull a health snapshot, and diagnose hardware, OS, thermal, storage, memory, network, and process issues — without unattended remote access.

Demo bays ship with simulated tickets so you can practice the workflow before you pair a real machine.

**Not SaaS. Not a backdoor.** The agent is read-mostly: no shell, no persistence, no OS command execution. Playbooks only mutate simulated snapshots.

## Price

| | |
| --- | --- |
| **Evaluation** | Free. Clone it, run it on your LAN, try the demo fleet. |
| **Shop · 1 bench** | **$149 USD** one-time. Unlimited consented pairings from that workstation. |
| **Shop pack · 3 benches** | **$349 USD** one-time. |

Pay by emailing **[deyoungjohn3@gmail.com](mailto:deyoungjohn3@gmail.com?subject=TECH-BENCH%20shop%20license)** with your business name and how many benches. Invoice comes back. Details: [`LICENSE-COMMERCIAL.md`](LICENSE-COMMERCIAL.md).

You keep running the software you already downloaded. There is no license server.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cd frontend && npm install && npm run build && cd ..
python run.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Loopback browsers unlock automatically. Token file: `data/bench.token`.

### Pair a real PC

On the bench, click **Pair remote PC** and copy the command. On the remote machine (operator-consented):

```bash
python agent/techbench_agent.py --server http://127.0.0.1:8000 --code ABCDE-FGHIJ --bench-token "$(cat data/bench.token)"
```

The agent uploads inventory + a diagnostic snapshot, then heartbeats telemetry.

### Docker

The image listens on `0.0.0.0` *inside* the container as uid `10001`. Publish loopback-only:

```bash
docker build -t tech-bench .
docker run --rm -p 127.0.0.1:8000:8000 -v techbench-data:/app/data tech-bench
```

Do not publish `0.0.0.0:8000:8000` unless you also understand the LAN opt-in and token gate.

### Two-process development

```bash
source .venv/bin/activate
PYTHONPATH=backend python -m uvicorn techbench.main:app --reload --host 127.0.0.1 --port 8000
# other terminal
cd frontend && npm install && npm run dev
```

Vite proxies `/api` (including WebSocket) to port 8000.

## What it does

- Occupies **bays** with this host (live `psutil` inventory) plus a demo fleet of sick and healthy PCs.
- Runs a shared **diagnostic engine** (SMART pre-fail, disk full, memory leaks, thermal throttle, APIPA/DNS/loss, lure-named processes, PSU rails, event-log correlation).
- Streams **1 Hz telemetry** over WebSocket onto an oscilloscope strip.
- Click subsystems on an ATX schematic, run a staged full scan, export a markdown service-tag report.
- Persists paired remotes, playbook state, notes, and the finding journal in `data/bench.sqlite`.
- Fleet triage: next-ticket, keyboard shortcuts (`?`), CPU sparklines, scan deltas, technician notes.

## Tests

```bash
source .venv/bin/activate
PYTHONPATH=backend pytest -q
```

CI runs pytest plus a frontend typecheck/build on every push.

## Layout

| Path | Role |
| --- | --- |
| `backend/techbench/persist.py` | SQLite bench memory |
| `backend/techbench/diagnostics/` | Collectors + rule engine |
| `backend/techbench/sim/` | Demo fleet with planted faults |
| `backend/techbench/main.py` | FastAPI + WebSocket |
| `agent/techbench_agent.py` | Consented remote reporter |
| `frontend/` | Bench UI |

## Safety

This is a **local technician console**. Cloning it from GitHub does not open a backdoor.

- Binds **127.0.0.1 only**. A public bind requires `TECHBENCH_ALLOW_LAN=1`.
- Every API call needs a session cookie or Bearer token.
- Agents may use HTTP only to localhost. Anything else must be **HTTPS** plus `--bench-token`.
- Pairing codes are 40-bit, single-use, 10 minutes, rate-limited.
- Playbooks change simulated snapshots only. Process collection stores the executable path, not argv.
- `data/` secrets are owner-read/write only. Docker runs as uid `10001`.

Use only on systems you own or are authorized to support.

## License

Evaluation and personal use: [`LICENSE`](LICENSE).  
Paid shop use: [`LICENSE-COMMERCIAL.md`](LICENSE-COMMERCIAL.md).
