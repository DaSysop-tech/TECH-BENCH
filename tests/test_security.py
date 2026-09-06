from __future__ import annotations

from pathlib import Path

import pytest

from techbench.security import (
    RateLimiter,
    assert_safe_bench_url,
    cors_allow_origins,
    host_header_ok,
    hostname_from_host_header,
    is_loopback_host,
    protect_secret_file,
    safe_dist_file,
    same_origin_ok,
    session_cookie_secure,
    websocket_origin_ok,
)


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
    with pytest.raises(ValueError):
        assert_safe_bench_url("http://127.evil.example")
    with pytest.raises(ValueError):
        assert_safe_bench_url("http://127.0.0.1.attacker.com")
    assert assert_safe_bench_url("http://127.0.0.1:8000") == "http://127.0.0.1:8000"
    assert assert_safe_bench_url("http://[::1]:8000") == "http://[::1]:8000"
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
    v6 = pair_agent_command("[::1]:8000", "A1B2C-D3E4F")
    assert "--server http://[::1]:8000" in v6


def test_anonymous_report_is_denied(anon):
    assert anon.get("/api/machines/sim-frontdesk/report").status_code == 401
    assert anon.get("/api/fleet").status_code == 401
    assert anon.post("/api/machines/sim-lab/notes", json={"body": "nope"}).status_code == 401


def test_host_header_parsing_handles_ipv6():
    assert hostname_from_host_header("[::1]:8000") == "::1"
    assert hostname_from_host_header("127.0.0.1:8000") == "127.0.0.1"
    assert hostname_from_host_header("localhost") == "localhost"
    assert host_header_ok("[::1]:8000")
    assert host_header_ok("127.0.0.1:8000")
    assert not host_header_ok("evil.example:8000")
    assert not host_header_ok("127.evil.example")
    assert not is_loopback_host("127.evil.example")
    assert is_loopback_host("::1")
    assert is_loopback_host("127.0.0.1")
    assert same_origin_ok("http://[::1]:8000", "[::1]:8000")
    assert websocket_origin_ok(None)
    assert websocket_origin_ok("http://127.0.0.1:8000")
    assert not websocket_origin_ok("http://evil.example")


def test_ipv6_loopback_host_header_allowed(client):
    assert client.get("/api/health", headers={"host": "[::1]:8000"}).status_code == 200
    assert client.get("/api/health", headers={"host": "evil.example:8000"}).status_code == 400


def test_security_headers_are_tight(client):
    r = client.get("/api/health")
    csp = r.headers.get("content-security-policy", "")
    assert "connect-src 'self'" in csp
    assert "ws:" not in csp
    assert "wss:" not in csp
    assert r.headers.get("x-frame-options") == "DENY"
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("cross-origin-opener-policy") == "same-origin"


def test_cors_rejects_wildcard():
    from techbench.security import DEFAULT_CORS

    origins = cors_allow_origins("*,http://127.0.0.1:8000,null")
    assert "*" not in origins
    assert "null" not in origins
    assert "http://127.0.0.1:8000" in origins
    assert cors_allow_origins("*") == [o.strip() for o in DEFAULT_CORS.split(",") if o.strip()]


def test_session_cookie_secure_flag(monkeypatch):
    monkeypatch.delenv("TECHBENCH_COOKIE_SECURE", raising=False)
    assert session_cookie_secure(https=False) is False
    assert session_cookie_secure(https=True) is True
    monkeypatch.setenv("TECHBENCH_COOKIE_SECURE", "1")
    assert session_cookie_secure(https=False) is True
    monkeypatch.setenv("TECHBENCH_COOKIE_SECURE", "0")
    assert session_cookie_secure(https=True) is False


def test_secret_files_are_owner_only(tmp_path: Path):
    secret = tmp_path / "bench.token"
    secret.write_text("secret\n")
    secret.chmod(0o644)
    protect_secret_file(secret)
    assert secret.stat().st_mode & 0o777 == 0o600


def test_sqlite_db_is_owner_only(tmp_path, monkeypatch):
    db = tmp_path / "bench.db"
    monkeypatch.setenv("TECHBENCH_PERSIST", "1")
    monkeypatch.setenv("TECHBENCH_DB", str(db))
    from techbench import persist

    persist.close()
    persist.init_db()
    persist.close()
    assert db.exists()
    assert db.stat().st_mode & 0o777 == 0o600


def test_existing_token_file_is_tightened(tmp_path, monkeypatch):
    token = tmp_path / "bench.token"
    token.write_text("already-set\n")
    token.chmod(0o644)
    monkeypatch.setattr("techbench.security.TOKEN_FILE", token)
    monkeypatch.delenv("TECHBENCH_TOKEN", raising=False)
    from techbench.security import ensure_bench_token

    assert ensure_bench_token() == "already-set"
    assert token.stat().st_mode & 0o777 == 0o600


def test_websocket_requires_auth(anon, client):
    with pytest.raises(Exception):
        with anon.websocket_connect("/api/ws/fleet"):
            pass
    with client.websocket_connect("/api/ws/fleet") as ws:
        payload = ws.receive_json()
        assert payload["type"] == "fleet"
