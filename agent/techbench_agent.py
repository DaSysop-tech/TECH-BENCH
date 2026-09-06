#!/usr/bin/env python3
"""TECH-BENCH remote diagnostic agent.

Run on a PC (with operator consent) to stream inventory, a diagnostic snapshot,
and live telemetry to a bench server. Pairing uses a short-lived code shown on
the bench — there is no unauthenticated remote access.

This agent is read-mostly: it reports health. It does not install persistence
or open reverse shells.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx

# Allow running from a source checkout: add backend/ to path.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from techbench.diagnostics.collectors import collect_local_snapshot, collect_local_telemetry  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="TECH-BENCH diagnostic agent")
    parser.add_argument("--server", required=True, help="Bench base URL, e.g. http://bench:8000")
    parser.add_argument("--code", required=True, help="Pairing code from the bench")
    parser.add_argument("--interval", type=float, default=2.0, help="Telemetry interval seconds")
    parser.add_argument(
        "--bench-token",
        default="",
        help="Optional TECHBENCH_TOKEN if the bench requires Bearer auth",
    )
    args = parser.parse_args()
    base = args.server.rstrip("/")
    headers = {}
    if args.bench_token:
        headers["Authorization"] = f"Bearer {args.bench_token}"

    snap = collect_local_snapshot()
    with httpx.Client(timeout=15, follow_redirects=False, headers=headers) as client:
        reg = client.post(
            f"{base}/api/agent/register",
            json={"code": args.code, "inventory": snap.inventory.model_dump(mode="json")},
        )
        if reg.status_code != 200:
            print(f"Pairing failed: {reg.status_code} {reg.text}", file=sys.stderr)
            return 1
        token = reg.json()["token"]
        machine = reg.json()["machine"]
        print(f"Paired as {machine['hostname']} ({machine['id']})", flush=True)

        posted = client.post(
            f"{base}/api/agent/snapshot",
            json={"token": token, "snapshot": snap.model_dump(mode="json")},
        )
        posted.raise_for_status()
        print("Initial diagnostic snapshot uploaded.", flush=True)

        while True:
            sample = collect_local_telemetry()
            r = client.post(
                f"{base}/api/agent/telemetry",
                json={"token": token, "sample": sample.model_dump(mode="json")},
            )
            if r.status_code != 200:
                print(f"Telemetry error: {r.status_code} {r.text}", file=sys.stderr)
                return 2
            time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
