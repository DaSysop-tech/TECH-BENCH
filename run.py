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
    host = os.environ.get("TECHBENCH_HOST", "0.0.0.0")
    port = int(os.environ.get("TECHBENCH_PORT", "8000"))
    uvicorn.run("techbench.main:app", host=host, port=port, reload=False)
