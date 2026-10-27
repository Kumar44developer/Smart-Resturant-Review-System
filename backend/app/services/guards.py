"""Request guards: output/input sanitization and a bounded in-memory rate limiter.

Treats all external review content as untrusted data. The rate limiter is
process-local (adequate for the single-machine SQLite deployment); a shared
Redis limiter is documented as the multi-process production alternative."""
from __future__ import annotations

import re
import time
from collections import defaultdict, deque

from ..config import settings

# Strip characters that could break out of HTML when we ever echo text unescaped.
_TAG_RE = re.compile(r"<[^>]*>")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def sanitize_text(text: str | None, *, limit: int = 5000) -> str:
    if not text:
        return ""
    cleaned = _CTRL_RE.sub("", text)
    cleaned = _TAG_RE.sub("", cleaned)
    return cleaned[:limit]


def escape_html(text: str) -> str:
    """Jinja auto-escapes, but this is used for any manual composition."""
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace('"', "&quot;").replace("'", "&#x27;"))


_buckets: dict[str, deque] = defaultdict(deque)


def rate_limit(key: str) -> None:
    """Raise if the caller exceeded RATE_LIMIT_PER_MIN. FastAPI turns the HTTP
    exception into a 429 response."""
    from fastapi import HTTPException, status
    now = time.monotonic()
    win = _buckets[key]
    while win and now - win[0] > 60.0:
        win.popleft()
    if len(win) >= settings.rate_limit_per_min:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded; slow down.")
    win.append(now)
