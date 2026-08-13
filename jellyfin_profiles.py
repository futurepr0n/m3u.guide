"""Persistent per-playlist Jellyfin export profiles."""

from __future__ import annotations

import json
from pathlib import Path
import re


_PROFILE = re.compile(r"^[a-z0-9_-]+$")
DEFAULT_PROFILE = {
    "name": "default",
    "live_group_prefixes": [],
    "movie_groups": [],
    "series_groups": [],
    "include_live": True,
    "include_movies": True,
    "include_series": True,
    "remove_missing_vod": True,
    "max_movies": None,
    "max_series": None,
    "max_episodes": None,
}


def load_profiles(playlist_dir: Path) -> dict[str, dict]:
    path = Path(playlist_dir) / "jellyfin_profiles.json"
    if not path.exists():
        return {"default": dict(DEFAULT_PROFILE)}
    data = json.loads(path.read_text(encoding="utf-8"))
    profiles = {}
    for name, supplied in data.get("profiles", {}).items():
        if not _PROFILE.fullmatch(name):
            continue
        profile = dict(DEFAULT_PROFILE)
        profile.update(supplied)
        profile["name"] = name
        profiles[name] = profile
    return profiles or {"default": dict(DEFAULT_PROFILE)}


def save_profile(playlist_dir: Path, name: str, supplied: dict) -> dict:
    if not _PROFILE.fullmatch(name):
        raise ValueError("profile name must contain only lowercase letters, numbers, _ or -")
    profiles = load_profiles(playlist_dir)
    profile = dict(DEFAULT_PROFILE)
    profile.update(supplied)
    profile["name"] = name
    for key in ("live_group_prefixes", "movie_groups", "series_groups"):
        profile[key] = sorted({str(value).strip() for value in profile.get(key, []) if str(value).strip()})
    for key in ("max_movies", "max_series", "max_episodes"):
        value = profile.get(key)
        profile[key] = max(1, int(value)) if value not in (None, "") else None
    profiles[name] = profile
    path = Path(playlist_dir) / "jellyfin_profiles.json"
    path.write_text(json.dumps({"profiles": profiles}, indent=2) + "\n", encoding="utf-8")
    return profile
