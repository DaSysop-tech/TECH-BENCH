from __future__ import annotations

from pathlib import Path

import pytest

from techbench.security import RateLimiter, assert_safe_bench_url, safe_dist_file


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


def test_pair_code_is_40_bit(client):
    r = client.post("/api/pair", json={"alias": "x", "location": "y"})
    assert r.status_code == 200
    code = r.json()["code"]
    compact = code.replace("-", "")
    assert len(compact) == 10
    int(compact, 16)


def test_pair_rate_limit():
    limiter = RateLimiter(3, 60)
    assert limiter.hit("a")
    assert limiter.hit("a")
    assert limiter.hit("a")
    assert limiter.hit("a") is False
    assert limiter.hit("b") is True


def test_anonymous_api_is_denied(anon):
    assert anon.get("/api/health").status_code == 200
    assert anon.get("/api/machines").status_code == 401
    assert anon.post("/api/pair", json={"alias": "x", "location": "y"}).status_code == 401
    assert anon.get("/api/machines?access_token=test-secret-token").status_code == 401


def test_session_cookie_unlocks(anon):
    denied = anon.get("/api/machines")
    assert denied.status_code == 401
    login = anon.post("/api/session", json={"token": "test-secret-token"})
    assert login.status_code == 200
    assert "techbench_session" in login.cookies
    ok = anon.get("/api/machines")
    assert ok.status_code == 200


def test_bad_session_token_rejected(anon):
    r = anon.post("/api/session", json={"token": "nope"})
    assert r.status_code == 401


def test_agent_refuses_plaintext_remote_url():
    with pytest.raises(ValueError):
        assert_safe_bench_url("http://evil.example:8000")
    with pytest.raises(ValueError):
        assert_safe_bench_url("file:///etc/passwd")
    assert assert_safe_bench_url("http://127.0.0.1:8000") == "http://127.0.0.1:8000"
    assert assert_safe_bench_url("https://bench.example").startswith("https://")


def test_pair_agent_command_uses_loopback_http():
    from techbench.security import pair_agent_command

    cmd = pair_agent_command("127.0.0.1:8000", "A1B2C-D3E4F")
    assert "--server http://127.0.0.1:8000" in cmd
    assert "--code A1B2C-D3E4F" in cmd
    assert "data/bench.token" in cmd
    dirty = pair_agent_command("evil.example; rm -rf /", "A1B2C-D3E4F")
    assert "evil.example" not in dirty
    assert "http://127.0.0.1:8000" in dirty


def test_anonymous_report_is_denied(anon):
    assert anon.get("/api/machines/sim-frontdesk/report").status_code == 401
