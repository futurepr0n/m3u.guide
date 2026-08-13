"""Helpers for publishing the Jellyfin plugin repository."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from urllib.parse import quote


PACKAGE_NAME = re.compile(r"^Jellyfin\.Plugin\.M3uGuide_[0-9]+(?:\.[0-9]+){3}\.zip$")


def package_filename(version: str) -> str:
    """Return the immutable package filename for a four-part plugin version."""
    filename = f"Jellyfin.Plugin.M3uGuide_{version}.zip"
    if not PACKAGE_NAME.fullmatch(filename):
        raise ValueError(f"Invalid plugin version: {version!r}")
    return filename


def build_manifest(manifest_path: Path, public_base_url: str, package_route: str) -> list:
    """Load a repository manifest and replace development package origins."""
    with manifest_path.open("r", encoding="utf-8") as stream:
        manifest = json.load(stream)

    result = copy.deepcopy(manifest)
    base = public_base_url.rstrip("/")
    route = package_route.strip("/")
    for plugin in result:
        plugin["imageUrl"] = f"{base}/{route}/m3u-logo.jpg"
        for version in plugin.get("versions", []):
            filename = package_filename(str(version.get("version", "")))
            version["sourceUrl"] = f"{base}/{route}/{quote(filename)}"
    return result
