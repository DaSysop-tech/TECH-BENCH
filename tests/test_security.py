from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from techbench.main import app
from techbench.security import RateLimiter, safe_dist_file


def test_safe_dist_blocks_traversal(tmp_path: Path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "ok.txt").write_text("hi")
    secret = tmp_path / "secret.txt"
    secret.write_text("nope")
    assert safe_dist_file(dist, "ok.txt") == (dist / "ok.txt").resolve()
    assert safe_dist_file(dist, "../secret.txt") is None
    assert safe_dist_file(dist, "..\\secret.txt") is None
    assert safe_dist_file(dist, "/etc/passwd") is None
    assert safe_dist_file(dist, "") is None


def test_pair_code_is_40_bit():
    with TestClient(app) as client:
        r = client.post("/api/pair", json={"alias": "x", "location": "y"})
        assert r.status_code == 200
        code = r.json()["code"]
        compact = code.replace("-", "")
        assert len(compact) == 10
        int(compact, 16)


def test_pair_rate_limit():
    limiter = RateLimiter(3, 60)
    assert limiter.hit()
    assert limiter.hit()
    assert limiter.hit()
    assert limiter.hit() is False


def test_process_snapshot_has_no_argv():
    from techbench.diagnostics.collectors import collect_local_snapshot

    snap = collect_local_snapshot()
    for proc in snap.processes:
        assert " --" not in (proc.path or "")
