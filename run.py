#!/usr/bin/env python3
"""Serve TECH-BENCH (API + built UI if present)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))

import uvicorn

if __name__ == "__main__":
    host = os.environ.get("TECHBENCH_HOST", "127.0.0.1")
    port = int(os.environ.get("TECHBENCH_PORT", "8000"))
    if host not in {"127.0.0.1", "localhost", "::1"} and not os.environ.get("TECHBENCH_TOKEN"):
        print(
            "WARNING: TECHBENCH_HOST is not loopback and TECHBENCH_TOKEN is unset. "
            "Anyone who can reach the port can drive the bench.",
            file=sys.stderr,
        )
    uvicorn.run("techbench.main:app", host=host, port=port, reload=False)
