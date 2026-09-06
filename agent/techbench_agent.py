from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from techbench.diagnostics.collectors import collect_local_snapshot, collect_local_telemetry  # noqa: E402
from techbench.security import TOKEN_FILE, assert_safe_bench_url  # noqa: E402


def _load_token(explicit: str) -> str:
    if explicit:
        return explicit
    env = os.environ.get("TECHBENCH_TOKEN", "").strip()
    if env:
        return env
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text(encoding="utf-8").strip()
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="TECH-BENCH diagnostic agent (read-only reporter)")
    parser.add_argument("--server", required=True, help="Bench base URL")
    parser.add_argument("--code", required=True, help="Pairing code from the bench")
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--bench-token", default="", help="Bench token (or TECHBENCH_TOKEN / data/bench.token)")
    args = parser.parse_args()
    if args.interval < 1 or args.interval > 60:
        print("interval must be 1-60 seconds", file=sys.stderr)
        return 1
    try:
        base = assert_safe_bench_url(args.server)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    host = (urlparse(base).hostname or "").lower()
    loopback = host in {"127.0.0.1", "localhost", "::1"}
    token = _load_token(args.bench_token)
    if not loopback and not token:
        print("Remote benches require --bench-token (this is not optional).", file=sys.stderr)
        return 1

    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    snap = collect_local_snapshot()
    with httpx.Client(timeout=15, follow_redirects=False, headers=headers) as client:
        reg = client.post(
            f"{base}/api/agent/register",
            json={"code": args.code, "inventory": snap.inventory.model_dump(mode="json")},
        )
        if reg.status_code != 200:
            print(f"Pairing failed: {reg.status_code} {reg.text}", file=sys.stderr)
            return 1
        agent_token = reg.json()["token"]
        machine = reg.json()["machine"]
        print(f"Paired as {machine['hostname']} ({machine['id']})", flush=True)

        posted = client.post(
            f"{base}/api/agent/snapshot",
            json={"token": agent_token, "snapshot": snap.model_dump(mode="json")},
        )
        posted.raise_for_status()
        print("Initial diagnostic snapshot uploaded.", flush=True)

        while True:
            sample = collect_local_telemetry()
            r = client.post(
                f"{base}/api/agent/telemetry",
                json={"token": agent_token, "sample": sample.model_dump(mode="json")},
            )
            if r.status_code != 200:
                print(f"Telemetry error: {r.status_code} {r.text}", file=sys.stderr)
                return 2
            time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
