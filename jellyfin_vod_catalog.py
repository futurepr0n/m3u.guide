"""Generate a full, paginated Jellyfin VOD catalog without hosting media."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path

from lxml import etree

from jellyfin_export import _jellyfin_stream_url, iter_m3u
from jellyfin_vod_export import _display_name, _episode_info, _movie_info, _safe, _stable_id
from provider_mirrors import rewrite_provider_url


def _nfo(root_name: str, values: dict[str, object]) -> str:
    root = etree.Element(root_name)
    for key, value in values.items():
        if value is None or value == "":
            continue
        child = etree.SubElement(root, key)
        child.text = str(value)
    return etree.tostring(root, encoding="unicode")


def _selected(group: str, selected_groups: list[str]) -> bool:
    return not selected_groups or group in selected_groups


def _below(count: int, limit: int | None) -> bool:
    return limit is None or count < limit


def generate_vod_catalog(
    playlist: Path,
    destination: Path,
    profile: dict,
    *,
    overrides_path: Path | None = None,
    stream_base: str | None = None,
    active_mirror: str | None = None,
) -> dict:
    """Stream all selected VOD entries into JSONL plus a revision manifest."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    catalog_path = destination / "vod.catalog.jsonl"
    overrides = {}
    item_overrides = {}
    if overrides_path and Path(overrides_path).exists():
        override_data = json.loads(Path(overrides_path).read_text(encoding="utf-8"))
        overrides = override_data.get("series_aliases", {})
        item_overrides = override_data.get("items", {})
    counts = Counter()
    series_written: set[str] = set()
    seasons_written: set[tuple[str, int]] = set()
    digest = hashlib.sha256()
    diagnostics_path = destination / "vod.parse-diagnostics.jsonl"

    with catalog_path.open("w", encoding="utf-8", newline="\n") as catalog, diagnostics_path.open("w", encoding="utf-8", newline="\n") as diagnostics:
        for entry in iter_m3u(Path(playlist)):
            group = entry.attributes.get("group-title", "")
            record = None
            if entry.content_kind == "movie" and profile.get("include_movies", True) and _selected(group, profile.get("movie_groups", [])) and _below(counts["movies"], profile.get("max_movies")):
                title, year = _movie_info(entry)
                item_id = _stable_id(entry)
                folder = f"Movies/{_safe(title)} [m3u-{item_id}]"
                record = {
                    "id": item_id,
                    "kind": "movie",
                    "relative_path": f"{folder}/movie.strm",
                    "stream_url": _jellyfin_stream_url(rewrite_provider_url(entry.url, stream_base, active_mirror)),
                    "nfo_relative_path": f"{folder}/movie.nfo",
                    "nfo": _nfo("movie", {
                        "title": title, "originaltitle": entry.attributes.get("tvg-name") or title,
                        "year": year, "genre": group, "tag": group,
                        "uniqueid": item_id, "thumb": entry.attributes.get("tvg-logo"),
                    }),
                }
                counts["movies"] += 1
            elif entry.content_kind == "series" and profile.get("include_series", True) and _selected(group, profile.get("series_groups", [])) and _below(counts["episodes"], profile.get("max_episodes")):
                counts["selected_series_entries"] += 1
                item_id = _stable_id(entry)
                parsed = _episode_info(entry)
                override = item_overrides.get(item_id)
                if override:
                    try:
                        parsed = (
                            str(override["series"]).strip(), int(override.get("season", 1)),
                            int(override["episode"]), str(override.get("episode_title") or f'Episode {override["episode"]}').strip(),
                            "stable source ID override",
                        )
                        counts["overrides_applied"] += 1
                    except (KeyError, TypeError, ValueError):
                        parsed = None
                if parsed is None or not parsed[0] or parsed[1] < 0 or parsed[2] < 1:
                    counts["unparsed_episodes"] += 1
                    diagnostic = {
                        "id": item_id,
                        "original_title": _display_name(entry),
                        "inferred_series": parsed[0] if parsed else None,
                        "season": parsed[1] if parsed else None,
                        "episode": parsed[2] if parsed else None,
                        "group": group,
                        "reason": "invalid stable-ID override" if override else "no supported episode marker",
                    }
                    diagnostics.write(json.dumps(diagnostic, ensure_ascii=False, separators=(",", ":")) + "\n")
                    continue
                series, season, episode, episode_title, parse_note = parsed
                counts["parsed_series_entries"] += 1
                series = overrides.get(series, series)
                series_id = hashlib.sha256(series.casefold().encode("utf-8")).hexdigest()[:24]
                if series_id not in series_written and not _below(counts["series"], profile.get("max_series")):
                    continue
                show = f"Shows/{_safe(series)} [m3u-{series_id}]"
                if series_id not in series_written:
                    show_record = {
                        "id": series_id, "kind": "series",
                        "relative_path": f"{show}/tvshow.nfo",
                        "content": _nfo("tvshow", {
                            "title": series, "originaltitle": entry.attributes.get("tvg-name") or series,
                            "genre": group, "tag": group, "uniqueid": series_id,
                            "thumb": entry.attributes.get("tvg-logo"),
                        }),
                    }
                    line = json.dumps(show_record, ensure_ascii=False, separators=(",", ":")) + "\n"
                    catalog.write(line)
                    digest.update(line.encode("utf-8"))
                    series_written.add(series_id)
                    counts["series"] += 1
                season_key = (series_id, season)
                if season_key not in seasons_written:
                    season_record = {
                        "id": f"{series_id}-season-{season}", "kind": "series",
                        "relative_path": f"{show}/Season {season:02d}/season.nfo",
                        "content": _nfo("season", {
                            "title": f"Season {season}", "seasonnumber": season,
                            "showtitle": series, "genre": group, "tag": group,
                            "uniqueid": f"{series_id}-season-{season}",
                            "thumb": entry.attributes.get("tvg-logo"),
                        }),
                    }
                    line = json.dumps(season_record, ensure_ascii=False, separators=(",", ":")) + "\n"
                    catalog.write(line)
                    digest.update(line.encode("utf-8"))
                    seasons_written.add(season_key)
                    counts["seasons"] += 1
                stem = f"S{season:02d}E{episode:03d} [m3u-{item_id}]"
                folder = f"{show}/Season {season:02d}"
                record = {
                    "id": item_id, "kind": "episode",
                    "relative_path": f"{folder}/{stem}.strm",
                    "stream_url": _jellyfin_stream_url(rewrite_provider_url(entry.url, stream_base, active_mirror)),
                    "nfo_relative_path": f"{folder}/{stem}.nfo",
                    "nfo": _nfo("episodedetails", {
                        "title": episode_title, "originaltitle": entry.attributes.get("tvg-name") or episode_title,
                        "showtitle": series, "season": season,
                        "episode": episode, "genre": group, "tag": group,
                        "uniqueid": item_id, "thumb": entry.attributes.get("tvg-logo"),
                    }),
                    "parse_note": parse_note,
                }
                counts["episodes"] += 1
            if record is not None:
                line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
                catalog.write(line)
                digest.update(line.encode("utf-8"))

    manifest = {
        "format": "m3u.guide-vod-catalog",
        "version": 1,
        "profile": profile["name"],
        "revision": digest.hexdigest(),
        "counts": dict(counts),
        "catalog_bytes": catalog_path.stat().st_size,
        "diagnostics_bytes": diagnostics_path.stat().st_size,
        "remove_missing": bool(profile.get("remove_missing_vod", True)),
    }
    (destination / "vod.manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def read_catalog_page(path: Path, cursor: int, limit: int) -> tuple[list[dict], int | None]:
    records = []
    with Path(path).open("rb") as catalog:
        catalog.seek(cursor)
        while len(records) < limit:
            line = catalog.readline()
            if not line:
                return records, None
            records.append(json.loads(line))
        next_cursor = catalog.tell()
        if not catalog.read(1):
            next_cursor = None
    return records, next_cursor
