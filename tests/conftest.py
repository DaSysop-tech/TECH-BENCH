"""Pytest path bootstrap and authenticated API client."""

import os
import sys
from pathlib import Path

os.environ.setdefault("TECHBENCH_TOKEN", "test-secret-token")
os.environ.setdefault("TECHBENCH_PERSIST", "0")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import pytest
from fastapi.testclient import TestClient

from techbench.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        c.headers["Authorization"] = "Bearer test-secret-token"
        yield c


@pytest.fixture
def anon():
    with TestClient(app) as c:
        yield c
