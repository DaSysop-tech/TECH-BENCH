from __future__ import annotations

import time
from collections import deque
from pathlib import Path


class RateLimiter:
    """Simple in-memory sliding window. Fine for a single-process bench."""

    def __init__(self, max_hits: int, window_sec: float) -> None:
        self.max_hits = max_hits
        self.window_sec = window_sec
        self._hits: deque[float] = deque()

    def hit(self) -> bool:
        """Return True if the caller is allowed."""
        now = time.time()
        cutoff = now - self.window_sec
        while self._hits and self._hits[0] < cutoff:
            self._hits.popleft()
        if len(self._hits) >= self.max_hits:
            return False
        self._hits.append(now)
        return True


def safe_dist_file(dist_root: Path, url_path: str) -> Path | None:
    """Resolve a static file under dist_root, or None if the path is unsafe/missing."""
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
