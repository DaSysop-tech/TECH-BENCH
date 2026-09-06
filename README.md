# TECH-BENCH

Virtual tech bench: a technician workstation that **pairs** to a PC (with consent), pulls a live health snapshot, and diagnoses hardware, OS, thermal, storage, memory, network, and process anomalies.

This is not unattended remote access. Machines join the bench through a short-lived pairing code and a read-mostly agent. Demo bays ship with simulated tickets so you can practice the workflow without a second PC.

## What it does

- Occupies **bays** with this host (live `psutil` inventory) plus a demo fleet of sick and healthy PCs.
- Runs a shared **diagnostic engine** (SMART pre-fail, disk full, memory leaks, thermal throttle, APIPA/DNS/loss, lure-named processes, PSU rails, event-log correlation).
- Streams **1 Hz telemetry** over WebSocket onto an oscilloscope strip.
- Lets you click subsystems on an ATX schematic, run a staged full scan, and apply playbooks on simulated machines.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cd frontend && npm install && npm run build && cd ..
python run.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

### Two-process development

```bash
source .venv/bin/activate
PYTHONPATH=backend python -m uvicorn techbench.main:app --reload --host 127.0.0.1 --port 8000
# other terminal
cd frontend && npm install && npm run dev
```

Vite proxies `/api` (including WebSocket) to port 8000.

### Pair a real PC

On the bench, click **Pair remote PC** and copy the code. On the remote machine (operator-consented):

```bash
python agent/techbench_agent.py --server http://127.0.0.1:8000 --code ABCDE-FGHIJ --bench-token "$(cat data/bench.token)"
```

The agent uploads inventory + a diagnostic snapshot, then heartbeats telemetry. It does not open a shell or install persistence.

Codes look like `A1B2C-D3E4F`. Remote (non-localhost) benches also require `--bench-token`.

## Tests

```bash
source .venv/bin/activate
PYTHONPATH=backend pytest -q
```

## Layout

| Path | Role |
| --- | --- |
| `backend/techbench/diagnostics/` | Collectors + rule engine |
| `backend/techbench/sim/` | Demo fleet with planted faults |
| `backend/techbench/main.py` | FastAPI + WebSocket |
| `agent/techbench_agent.py` | Consented remote reporter |
| `frontend/` | Bench UI |

## Safety

This is a **local technician console**, not internet SaaS. Cloning it from GitHub does not open a backdoor: the agent never runs commands, never installs persistence, and never opens a shell.

Hard defaults:

- Binds **127.0.0.1 only**. A public bind requires `TECHBENCH_ALLOW_LAN=1`.
- Every API call needs a session cookie or Bearer token. Loopback browsers unlock automatically; anyone else pastes `data/bench.token`.
- Agents may use HTTP only to localhost. Anything else must be **HTTPS** and must send `--bench-token`.
- Pairing codes are 40-bit, single-use, 10 minutes, rate-limited per client IP.
- Playbooks change simulated snapshots only.
- Process collection stores the executable path, not argv.
- OpenAPI docs are off unless `TECHBENCH_DEBUG=1`.

Use only on systems you own or are authorized to support.
