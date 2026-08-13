"""Validated provider-origin selection and non-destructive URL rewriting."""

from __future__ import annotations

from urllib.parse import quote, urlsplit


def normalize_origin(value: str | None) -> str | None:
    """Return a canonical HTTP(S) origin, rejecting credentials and paths."""
    if not value:
        return None
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Provider mirror must be an absolute HTTP or HTTPS origin")
    if parsed.username or parsed.password:
        raise ValueError("Provider mirror must not contain credentials")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("Provider mirror must contain only scheme, host, and optional port")
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def normalize_mirrors(values: list[str]) -> list[str]:
    """Validate, canonicalize, and de-duplicate an ordered mirror list."""
    result = []
    seen = set()
    for value in values:
        origin = normalize_origin(value)
        key = origin.casefold()
        if key not in seen:
            result.append(origin)
            seen.add(key)
    return result


def rewrite_provider_url(url: str, source_origin: str | None, active_origin: str | None) -> str:
    """Replace only the configured provider origin, including proxy-encoded URLs."""
    source = normalize_origin(source_origin)
    active = normalize_origin(active_origin)
    if not source or not active or source.casefold() == active.casefold():
        return url
    encoded_source = quote(source, safe="/")
    encoded_active = quote(active, safe="/")
    return url.replace(encoded_source, encoded_active).replace(source, active)
