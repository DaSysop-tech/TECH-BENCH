from __future__ import annotations

import hmac
import os
import re
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
TOKEN_FILE = Path(os.environ.get("TECHBENCH_TOKEN_FILE", ROOT / "data" / "bench.token"))
SESSION_COOKIE = "techbench_session"
SESSION_TTL_SEC = 12 * 3600
MAX_BODY_BYTES = 256 * 1024
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

_sessions: dict[str, float] = {}


class RateLimiter:
    """Sliding window. Pass a key (client IP) to isolate callers."""

    def __init__(self, max_hits: int, window_sec: float) -> None:
        self.max_hits = max_hits
        self.window_sec = window_sec
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def hit(self, key: str = "global") -> bool:
        now = time.time()
        cutoff = now - self.window_sec
        bucket = self._hits[key]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= self.max_hits:
            return False
        bucket.append(now)
        return True


def safe_dist_file(dist_root: Path, url_path: str) -> Path | None:
    if not url_path or url_path.endswith("/"):
        return None
    raw = Path(url_path)
    if raw.is_absolute() or ".." in raw.parts:
        return None
    try:
        dist = dist_root.resolve()
        candidate = (dist / url_path).resolve()
        candidate.relative_to(dist)
    except (OSError, ValueError):
        return None
    if candidate.is_file():
        return candidate
    return None


def ensure_bench_token() -> str:
    env = os.environ.get("TECHBENCH_TOKEN", "").strip()
    if env:
        return env
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    if TOKEN_FILE.exists():
        stored = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if stored:
            return stored
    token = secrets.token_urlsafe(32)
    TOKEN_FILE.write_text(token + "\n", encoding="utf-8")
    try:
        TOKEN_FILE.chmod(0o600)
    except OSError:
        pass
    return token


def token_ok(provided: str | None, expected: str) -> bool:
    if not provided or not expected:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


def issue_session() -> str:
    sid = secrets.token_urlsafe(24)
    _sessions[sid] = time.time() + SESSION_TTL_SEC
    return sid


def session_ok(sid: str | None) -> bool:
    if not sid:
        return False
    exp = _sessions.get(sid)
    if exp is None or exp < time.time():
        _sessions.pop(sid, None)
        return False
    return True


def drop_session(sid: str | None) -> None:
    if sid:
        _sessions.pop(sid, None)


def client_ip(host: str | None) -> str:
    return (host or "unknown").split("%")[0]


def is_loopback_ip(ip: str | None) -> bool:
    ip = (ip or "").lower()
    return ip in LOOPBACK_HOSTS or ip.startswith("127.")


def host_header_ok(host: str | None) -> bool:
    raw = (host or "").split(":")[0].lower()
    extra = {
        h.strip().lower()
        for h in os.environ.get("TECHBENCH_ALLOWED_HOSTS", "").split(",")
        if h.strip()
    }
    return raw in LOOPBACK_HOSTS | extra | {"testserver"}


def same_origin_ok(origin: str | None, host: str | None) -> bool:
    if not origin:
        return False
    try:
        parsed = urlparse(origin)
    except ValueError:
        return False
    origin_host = (parsed.hostname or "").lower()
    req_host = (host or "").split(":")[0].lower()
    if origin_host not in LOOPBACK_HOSTS:
        return False
    return req_host in LOOPBACK_HOSTS | {"testserver"}


_HOST_HEADER = re.compile(r"^(?:\[[0-9a-fA-F:]+\]|[A-Za-z0-9.-]+)(?::\d{1,5})?$")


def pair_agent_command(host_header: str | None, code: str) -> str:
    """Build a copy-paste agent command. Never embeds the bench token itself."""
    host = (host_header or "").strip()
    if not _HOST_HEADER.fullmatch(host):
        host = "127.0.0.1:8000"
    if host.startswith("["):
        hostname = host.split("]")[0].lstrip("[").lower()
    else:
        hostname = host.split(":")[0].lower()
    loopback = hostname in LOOPBACK_HOSTS or hostname.startswith("127.")
    scheme = "http" if loopback else "https"
    token_arg = '"$(cat data/bench.token)"' if loopback else "BENCH_TOKEN"
    return (
        f"python agent/techbench_agent.py --server {scheme}://{host} "
        f"--code {code} --bench-token {token_arg}"
    )


def assert_safe_bench_url(url: str) -> str:
    """Agents may only speak HTTPS, or HTTP to loopback. No redirects, no other schemes."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Bench URL must be http:// or https://")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("Bench URL is missing a host")
    loopback = host in LOOPBACK_HOSTS or host.startswith("127.")
    if parsed.scheme == "http" and not loopback:
        raise ValueError("Refusing plaintext HTTP except to localhost")
    if parsed.username or parsed.password:
        raise ValueError("Bench URL must not contain credentials")
    return url.rstrip("/")


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self'; "
        "img-src 'self' data:; "
        "connect-src 'self' ws: wss:; "
        "font-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    ),
}
