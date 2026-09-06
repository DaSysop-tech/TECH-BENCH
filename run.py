#!/usr/bin/env python3
"""Serve TECH-BENCH (API + built UI if present)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))

import uvicorn

from techbench.security import LOOPBACK_HOSTS, TOKEN_FILE, ensure_bench_token

if __name__ == "__main__":
    host = os.environ.get("TECHBENCH_HOST", "127.0.0.1")
    port = int(os.environ.get("TECHBENCH_PORT", "8000"))
    public = host not in LOOPBACK_HOSTS
    if public and os.environ.get("TECHBENCH_ALLOW_LAN") != "1":
        print(
            "Refusing to bind a non-loopback address.\n"
            "This bench is a local console. To opt in to LAN listen:\n"
            "  TECHBENCH_ALLOW_LAN=1 TECHBENCH_HOST=0.0.0.0 python run.py",
            file=sys.stderr,
        )
        raise SystemExit(2)
    ensure_bench_token()
    print(f"TECH-BENCH on http://{host}:{port}", flush=True)
    print(f"Loopback browser sessions unlock automatically. Token file: {TOKEN_FILE}", flush=True)
    if public:
        print("LAN bind enabled. Agents must pass --bench-token.", flush=True)
    uvicorn.run("techbench.main:app", host=host, port=port, reload=False)
