from __future__ import annotations

import hmac
import ipaddress
import os
import re
import secrets
import stat
import time
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
TOKEN_FILE = Path(os.environ.get("TECHBENCH_TOKEN_FILE", DATA_DIR / "bench.token"))
SESSION_COOKIE = "techbench_session"
SESSION_TTL_SEC = 12 * 3600
MAX_BODY_BYTES = 256 * 1024
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
DEFAULT_CORS = (
    "http://127.0.0.1:8000,http://localhost:8000,"
    "http://127.0.0.1:5173,http://localhost:5173,"
    "http://[::1]:8000,http://[::1]:5173"
)

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


def protect_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(stat.S_IRWXU)
    except OSError:
        pass


def protect_secret_file(path: Path) -> None:
    """Owner-only files. Never chmod a parent like /tmp."""
    try:
        if path.exists() and path.is_file():
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    for extra in (Path(str(path) + "-wal"), Path(str(path) + "-shm"), Path(str(path) + "-journal")):
        try:
            if extra.exists() and extra.is_file():
                extra.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass


def protect_data_parent_if_ours(path: Path) -> None:
    try:
        parent = path.parent.resolve()
        data = DATA_DIR.resolve()
    except OSError:
        return
    if parent == data:
        protect_private_dir(parent)


def ensure_bench_token() -> str:
    env = os.environ.get("TECHBENCH_TOKEN", "").strip()
    if TOKEN_FILE.exists():
        protect_data_parent_if_ours(TOKEN_FILE)
        protect_secret_file(TOKEN_FILE)
    if env:
        return env
    protect_data_parent_if_ours(TOKEN_FILE)
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    if TOKEN_FILE.exists():
        stored = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if stored:
            protect_secret_file(TOKEN_FILE)
            return stored
    token = secrets.token_urlsafe(32)
    TOKEN_FILE.write_text(token + "\n", encoding="utf-8")
    protect_secret_file(TOKEN_FILE)
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


def hostname_from_host_header(host_header: str | None) -> str:
    """Parse Host / :authority. Understands [::1]:8000, not just host:port IPv4."""
    raw = (host_header or "").strip().lower()
    if not raw:
        return ""
    if raw.startswith("["):
        end = raw.find("]")
        if end < 1:
            return ""
        return raw[1:end]
    if raw.count(":") == 1:
        host, _, port = raw.partition(":")
        if port.isdigit():
            return host
    return raw


def is_loopback_host(host: str | None) -> bool:
    """True only for localhost or actual loopback IPs. 127.evil.example is not loopback."""
    raw = (host or "").strip().lower().rstrip(".")
    if not raw:
        return False
    if raw in {"localhost", "localhost."}:
        return True
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    if "%" in raw:
        raw = raw.split("%", 1)[0]
    if raw.startswith("::ffff:"):
        raw = raw[7:]
    try:
        return ipaddress.ip_address(raw).is_loopback
    except ValueError:
        return False


def is_loopback_ip(ip: str | None) -> bool:
    return is_loopback_host(ip)


def allowed_hostnames() -> set[str]:
    extra = {
        h.strip().lower()
        for h in os.environ.get("TECHBENCH_ALLOWED_HOSTS", "").split(",")
        if h.strip()
    }
    extra.add("testserver")
    return extra


def host_header_ok(host_header: str | None) -> bool:
    host = hostname_from_host_header(host_header)
    if not host:
        return False
    return is_loopback_host(host) or host in allowed_hostnames()


def websocket_origin_ok(origin: str | None) -> bool:
    """Browsers send Origin on WS. Missing Origin is allowed for Bearer agents."""
    if not origin:
        return True
    try:
        parsed = urlparse(origin)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    return host_header_ok(parsed.netloc)


def same_origin_ok(origin: str | None, host: str | None) -> bool:
    if not origin:
        return False
    try:
        parsed = urlparse(origin)
    except ValueError:
        return False
    origin_host = (parsed.hostname or "").lower()
    req_host = hostname_from_host_header(host)
    if not is_loopback_host(origin_host):
        return False
    return is_loopback_host(req_host) or req_host in {"testserver"}


def cors_allow_origins(raw: str | None = None) -> list[str]:
    text = os.environ.get("TECHBENCH_CORS", DEFAULT_CORS) if raw is None else raw
    origins = [o.strip() for o in text.split(",") if o.strip()]
    cleaned = [o for o in origins if o != "*" and o.lower() != "null"]
    if cleaned:
        return cleaned
    return [o.strip() for o in DEFAULT_CORS.split(",") if o.strip()]


def session_cookie_secure(*, https: bool = False) -> bool:
    flag = os.environ.get("TECHBENCH_COOKIE_SECURE", "").strip().lower()
    if flag in {"1", "true", "yes"}:
        return True
    if flag in {"0", "false", "no"}:
        return False
    return https


_HOST_HEADER = re.compile(r"^(?:\[[0-9a-fA-F:]+\]|[A-Za-z0-9.-]+)(?::\d{1,5})?$")


def pair_agent_command(host_header: str | None, code: str) -> str:
    """Build a copy-paste agent command. Never embeds the bench token itself."""
    host = (host_header or "").strip()
    if not _HOST_HEADER.fullmatch(host):
        host = "127.0.0.1:8000"
    hostname = hostname_from_host_header(host)
    loopback = is_loopback_host(hostname)
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
    loopback = is_loopback_host(host)
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
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "X-Permitted-Cross-Domain-Policies": "none",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "font-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    ),
}
