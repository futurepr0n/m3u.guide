"""Rate limiting and secret redaction for sensitive integration surfaces."""

from __future__ import annotations

from collections import defaultdict, deque
import re
from threading import Lock
from time import monotonic
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_SECRET_KEYS = {"password", "username", "token", "access_token", "stream_token"}
_URL = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]+")
_buckets: dict[str, deque[float]] = defaultdict(deque)
_bucket_lock = Lock()


def redact_url(value: str) -> str:
    """Redact sensitive query parameters and Xtream path credentials."""
    parsed = urlsplit(value)
    query = [(key, "[REDACTED]" if key.casefold() in _SECRET_KEYS else item) for key, item in parse_qsl(parsed.query, keep_blank_values=True)]
    path = re.sub(r"(?i)/(live|movie|series)/[^/]+/[^/]+/", r"/\1/[REDACTED]/[REDACTED]/", parsed.path)
    path = re.sub(r"(?i)^/stream/[^/]+/", "/stream/[REDACTED]/", path)
    return urlunsplit((parsed.scheme, parsed.netloc, path, urlencode(query), parsed.fragment))


def redact_secrets(value: object) -> str:
    """Return a log-safe exception or message string."""
    text = _BEARER.sub(r"\1[REDACTED]", str(value))
    return _URL.sub(lambda match: redact_url(match.group(0)), text)


def redact_data(value):
    """Recursively redact secret-bearing strings from API response data."""
    if isinstance(value, dict):
        return {key: ("[REDACTED]" if str(key).casefold() in _SECRET_KEYS else redact_data(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_data(item) for item in value]
    if isinstance(value, str):
        return redact_secrets(value)
    return value


def rate_limit(key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
    """Apply a bounded in-process sliding-window limit."""
    now = monotonic()
    with _bucket_lock:
        bucket = _buckets[key]
        while bucket and bucket[0] <= now - window_seconds:
            bucket.popleft()
        if len(bucket) >= limit:
            return False, max(1, round(window_seconds - (now - bucket[0])))
        bucket.append(now)
        return True, 0
