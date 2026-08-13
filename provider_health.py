"""Credential-safe Xtream provider health probes."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from time import monotonic
from urllib.parse import urlencode

import requests


def _classification(status: int, body: bytes, expects_entries: bool) -> tuple[bool, str]:
    folded = body.strip().lower()
    if status == 520:
        return False, "cloudflare_origin_error"
    if status == 429:
        return False, "throttled"
    if status in {401, 403}:
        return False, "authentication_failed"
    if status < 200 or status >= 300:
        return False, "http_error"
    if b"auth" in folded and (b"false" in folded or b"fail" in folded):
        return False, "authentication_failed"
    if expects_entries and folded in {b"", b"[]", b"{}"}:
        return False, "empty_catalog"
    return True, "healthy"


def _probe(name: str, url: str, headers: dict[str, str], expects_entries: bool) -> dict:
    started = monotonic()
    try:
        with requests.get(url, headers=headers, timeout=(5, 12), stream=True) as response:
            body = response.raw.read(16384, decode_content=True)
            ok, classification = _classification(response.status_code, body, expects_entries)
            return {
                "name": name,
                "ok": ok,
                "status": response.status_code,
                "classification": classification,
                "elapsed_ms": round((monotonic() - started) * 1000),
            }
    except requests.Timeout:
        classification = "timeout"
    except requests.ConnectionError:
        classification = "connection_failed"
    except requests.RequestException:
        classification = "request_failed"
    return {
        "name": name,
        "ok": False,
        "status": None,
        "classification": classification,
        "elapsed_ms": round((monotonic() - started) * 1000),
    }


def probe_xtream_provider(
    origin: str,
    username: str,
    password: str,
    *,
    user_agent: str,
    media_url: str | None = None,
) -> dict:
    """Probe independent Xtream surfaces without returning sensitive URLs."""
    credentials = urlencode({"username": username, "password": password})
    api = f"{origin}/player_api.php?{credentials}"
    targets = [
        ("account", api, False),
        ("live_api", f"{api}&action=get_live_streams", True),
        ("vod_api", f"{api}&action=get_vod_streams", True),
        ("series_api", f"{api}&action=get_series", True),
        ("m3u", f"{origin}/get.php?{credentials}&type=m3u_plus&output=ts", True),
        ("xmltv", f"{origin}/xmltv.php?{credentials}", False),
    ]
    if media_url:
        targets.append(("media", media_url, True))
    headers = {"User-Agent": user_agent, "Connection": "close", "Range": "bytes=0-16383"}
    with ThreadPoolExecutor(max_workers=len(targets)) as executor:
        results = list(executor.map(lambda item: _probe(item[0], item[1], headers, item[2]), targets))
    return {
        "origin": origin,
        "user_agent": user_agent,
        "checks": results,
        "healthy": all(item["ok"] for item in results),
    }
