"""Validate the hosted Jellyfin plugin repository before deployment."""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

from plugin_repository import package_filename


def validate(root: Path) -> list[str]:
    """Validate manifest metadata, immutable packages, and catalog artwork."""
    errors: list[str] = []
    manifest_path = root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"cannot read manifest.json: {error}"]

    if not isinstance(manifest, list) or not manifest:
        return ["manifest.json must contain at least one plugin"]

    for plugin in manifest:
        image_url = str(plugin.get("imageUrl", ""))
        if not image_url.endswith("/m3u-logo.jpg") or not (root / "m3u-logo.jpg").is_file():
            errors.append("catalog imageUrl or m3u-logo.jpg is missing")

        seen: set[str] = set()
        for release in plugin.get("versions", []):
            version = str(release.get("version", ""))
            if version in seen:
                errors.append(f"duplicate release {version}")
                continue
            seen.add(version)
            try:
                filename = package_filename(version)
            except ValueError as error:
                errors.append(str(error))
                continue
            package = root / filename
            if not package.is_file():
                errors.append(f"{version}: package is missing")
                continue
            checksum = hashlib.md5(package.read_bytes()).hexdigest().upper()
            if checksum != str(release.get("checksum", "")).upper():
                errors.append(f"{version}: checksum mismatch")
            try:
                with zipfile.ZipFile(package) as archive:
                    names = set(archive.namelist())
                    required = {"Jellyfin.Plugin.M3uGuide.dll", "meta.json"}
                    if not required.issubset(names):
                        errors.append(f"{version}: package contents are incomplete")
                    metadata = json.loads(archive.read("meta.json"))
                    if str(metadata.get("version")) != version:
                        errors.append(f"{version}: meta.json version mismatch")
                    image_path = metadata.get("imagePath")
                    if image_path and image_path not in names:
                        errors.append(f"{version}: declared plugin image is missing")
            except (OSError, zipfile.BadZipFile, KeyError, json.JSONDecodeError) as error:
                errors.append(f"{version}: invalid package: {error}")
    return errors


if __name__ == "__main__":
    repository = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "static" / "plugin-repository"
    failures = validate(repository)
    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        raise SystemExit(1)
    print(f"Jellyfin plugin repository validated: {repository}")

