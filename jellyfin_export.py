"""Generate Jellyfin-specific artifacts from an edited m3u.guide playlist."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
from typing import Iterator
from urllib.parse import unquote, urlsplit, urlunsplit

from lxml import etree
from provider_mirrors import rewrite_provider_url


_ATTRIBUTE_RE = re.compile(r'([A-Za-z0-9_-]+)="([^"]*)"')
_TVG_CHNO_RE = re.compile(r'\s+tvg-chno="[^"]*"', re.IGNORECASE)
_M3UGUIDE_ID_RE = re.compile(r'\s+x-m3uguide-id="[^"]*"', re.IGNORECASE)

_CATEGORY_KEYWORDS = {
    "Movie": ("movie", "movies", "cinema", "film"),
    "Kids": ("kid", "kids", "children", "childrens", "family", "disney"),
    "News": ("news", "journalism", "current affairs"),
    "Sports": (
        "sport", "sports", "football", "soccer", "basketball", "baseball",
        "hockey", "cfl", "dazn", "fubo", "sportsnet", "tsn", "victory+",
        "whl", "cbc ppv", "canada west ppv", "prime",
        "ufc", "boxing", "box office", "matchroom", "triller", "fight pass",
        "wwe", "aew", "mma", "espn+ ppv", "sports ppv", "ppv event",
    ),
}


@dataclass(frozen=True)
class M3uEntry:
    extinf: str
    url: str
    attributes: dict[str, str]

    @property
    def content_kind(self) -> str:
        explicit_kind = self.attributes.get("x-m3uguide-kind", "").strip().casefold()
        if explicit_kind in {"live", "movie", "series"}:
            return explicit_kind

        # Proxy URLs carry the provider URL in a percent-encoded query value, so
        # inspect the decoded URL as well as ordinary direct Xtream paths.
        candidate = unquote(self.url).casefold()
        if "/movie/" in candidate:
            return "movie"
        if "/series/" in candidate:
            return "series"
        return "live"


def iter_m3u(path: Path) -> Iterator[M3uEntry]:
    """Stream complete EXTINF/URL pairs from an M3U playlist."""
    pending: tuple[str, dict[str, str]] | None = None
    with path.open("r", encoding="utf-8-sig", errors="replace") as source:
        header = source.readline().strip()
        if not header.upper().startswith("#EXTM3U"):
            raise ValueError(f"{path} does not begin with #EXTM3U")

        for raw_line in source:
            line = raw_line.strip()
            if line.upper().startswith("#EXTINF:"):
                attributes = {
                    key.casefold(): value for key, value in _ATTRIBUTE_RE.findall(line)
                }
                pending = (line, attributes)
            elif line and not line.startswith("#") and pending is not None:
                extinf, attributes = pending
                yield M3uEntry(extinf=extinf, url=line, attributes=attributes)
                pending = None


def _jellyfin_extinf(entry: M3uEntry, channel_number: int) -> str:
    """Add Jellyfin ordering and a provisional stable source identifier."""
    line = _TVG_CHNO_RE.sub("", entry.extinf)
    line = _M3UGUIDE_ID_RE.sub("", line)
    source_id = hashlib.sha256(entry.url.encode("utf-8")).hexdigest()[:24]
    comma = line.rfind(",")
    if comma < 0:
        raise ValueError("EXTINF line has no display-name separator")
    return (
        f'{line[:comma]} tvg-chno="{channel_number}" '
        f'x-m3uguide-id="{source_id}"{line[comma:]}'
    )


def _jellyfin_stream_url(url: str) -> str:
    """Avoid an HTTP redirect before Jellyfin/FFmpeg reaches our proxy."""
    parsed = urlsplit(url)
    if parsed.scheme.casefold() == "http" and parsed.hostname == "m3u.futurepr0n.com":
        parsed = parsed._replace(scheme="https")
        return urlunsplit(parsed)
    return url


def _group_categories(group: str) -> set[str]:
    """Return raw group facets plus Jellyfin's canonical programme categories."""
    facets = {part.strip() for part in re.split(r"[|,]", group) if part.strip()}
    searchable = " ".join(facets).casefold()
    categories = set(facets)
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(keyword in searchable for keyword in keywords):
            categories.add(category)
    return categories


def _matches_group_prefix(group: str, group_prefixes: tuple[str, ...]) -> bool:
    if not group_prefixes:
        return True
    first_facet = re.split(r"[|,]", group, maxsplit=1)[0].strip()
    return any(
        group.casefold() == prefix.strip().casefold()
        or first_facet.casefold().startswith(prefix.strip().casefold())
        for prefix in group_prefixes
    )


def _write_live_m3u(
    source: Path,
    destination: Path,
    group_prefixes: tuple[str, ...],
    stream_base: str | None = None,
    active_mirror: str | None = None,
) -> tuple[dict, dict[str, str], dict[str, set[str]]]:
    counts = Counter()
    epg_ids: dict[str, str] = {}
    epg_categories: dict[str, set[str]] = {}
    groups = set()
    with destination.open("w", encoding="utf-8", newline="\n") as output:
        output.write("#EXTM3U\n")
        for entry in iter_m3u(source):
            counts[f"source_{entry.content_kind}"] += 1
            if entry.content_kind != "live":
                continue

            group = entry.attributes.get("group-title", "").strip()
            if not _matches_group_prefix(group, group_prefixes):
                counts["excluded_by_group"] += 1
                continue

            counts["exported_live"] += 1
            tvg_id = entry.attributes.get("tvg-id", "").strip()
            if tvg_id:
                folded_id = tvg_id.casefold()
                epg_ids.setdefault(folded_id, tvg_id)
                epg_categories.setdefault(folded_id, set()).update(
                    _group_categories(entry.attributes.get("group-title", ""))
                )
            else:
                counts["live_without_tvg_id"] += 1
            if group:
                groups.add(group)
            else:
                counts["live_without_group"] += 1

            output.write(_jellyfin_extinf(entry, counts["exported_live"]))
            output.write("\n")
            output.write(_jellyfin_stream_url(rewrite_provider_url(entry.url, stream_base, active_mirror)))
            output.write("\n")

    counts["exported_groups"] = len(groups)
    counts["unique_epg_ids"] = len(epg_ids)
    return dict(counts), epg_ids, epg_categories


def _write_trimmed_xmltv(
    source: Path,
    destination: Path,
    epg_ids: dict[str, str],
    epg_categories: dict[str, set[str]],
) -> dict:
    counts = Counter()
    written_channels: set[str] = set()
    programme_ids: set[str] = set()

    with etree.xmlfile(str(destination), encoding="utf-8") as output:
        output.write_declaration()
        with output.element(
            "tv",
            attrib={
                "generator-info-name": "m3u.guide Jellyfin export",
                "generator-info-url": "https://m3u.guide",
            },
        ):
            context = etree.iterparse(
                str(source), events=("end",), tag=("channel", "programme"), recover=True
            )
            for _, element in context:
                tag = etree.QName(element).localname
                if tag == "channel":
                    source_id = (element.get("id") or "").strip()
                    folded = source_id.casefold()
                    if folded in epg_ids and folded not in written_channels:
                        element.set("id", epg_ids[folded])
                        output.write(element)
                        written_channels.add(folded)
                        counts["channels"] += 1
                    elif folded in written_channels:
                        counts["duplicate_channels_removed"] += 1
                else:
                    source_id = (element.get("channel") or "").strip()
                    folded = source_id.casefold()
                    if folded in epg_ids:
                        element.set("channel", epg_ids[folded])
                        existing = {
                            (category.text or "").strip().casefold()
                            for category in element.findall("category")
                        }
                        for category in sorted(epg_categories.get(folded, set())):
                            if category.casefold() not in existing:
                                child = etree.SubElement(element, "category")
                                child.text = category
                                counts["categories_added"] += 1
                        output.write(element)
                        programme_ids.add(folded)
                        counts["programmes"] += 1

                element.clear()
                parent = element.getparent()
                if parent is not None:
                    while element.getprevious() is not None:
                        del parent[0]

    counts["requested_channel_ids"] = len(epg_ids)
    counts["matched_channel_ids"] = len(written_channels)
    counts["channel_ids_with_programmes"] = len(programme_ids)
    counts["channel_ids_missing_from_xmltv"] = len(set(epg_ids) - written_channels)
    counts["channel_ids_without_programmes"] = len(set(epg_ids) - programme_ids)
    return dict(counts)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def generate_jellyfin_export(
    playlist_dir: Path,
    public_base_url: str | None = None,
    *,
    profile: str = "default",
    group_prefixes: tuple[str, ...] = (),
    stream_base: str | None = None,
    active_mirror: str | None = None,
) -> dict:
    """Generate and publish a default Jellyfin export revision.

    The edited playlist is authoritative when present; otherwise the immutable
    source is used for a first preview export.
    """
    playlist_dir = Path(playlist_dir)
    edited = playlist_dir / "tv_edited.m3u"
    m3u_source = edited if edited.exists() else playlist_dir / "tv.m3u"
    xml_source = playlist_dir / "epg.xml"
    if not m3u_source.exists():
        raise FileNotFoundError(f"M3U source not found: {m3u_source}")
    if not xml_source.exists():
        raise FileNotFoundError(f"XMLTV source not found: {xml_source}")

    if not re.fullmatch(r"[a-z0-9_-]+", profile):
        raise ValueError("profile must contain only lowercase letters, numbers, _ or -")
    export_dir = playlist_dir / "exports" / "jellyfin" / profile
    export_dir.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".jellyfin-export-", dir=export_dir.parent))
    try:
        live_path = staging / "live.m3u8"
        epg_path = staging / "epg.xml"
        m3u_counts, epg_ids, epg_categories = _write_live_m3u(
            m3u_source, live_path, group_prefixes, stream_base, active_mirror
        )
        xml_counts = _write_trimmed_xmltv(
            xml_source, epg_path, epg_ids, epg_categories
        )

        warnings = []
        if m3u_counts.get("live_without_tvg_id"):
            warnings.append(
                f'{m3u_counts["live_without_tvg_id"]} live entries have no tvg-id'
            )
        if xml_counts.get("channel_ids_missing_from_xmltv"):
            warnings.append(
                f'{xml_counts["channel_ids_missing_from_xmltv"]} tvg-id values are absent from XMLTV'
            )
        if xml_counts.get("channel_ids_without_programmes"):
            warnings.append(
                f'{xml_counts["channel_ids_without_programmes"]} tvg-id values have no programmes'
            )

        validation = {
            "source": m3u_source.name,
            "m3u": m3u_counts,
            "xmltv": xml_counts,
            "warnings": warnings,
        }
        (staging / "validation.json").write_text(
            json.dumps(validation, indent=2), encoding="utf-8"
        )

        generated_at = datetime.now(timezone.utc).isoformat()
        artifacts = {}
        for name in ("live.m3u8", "epg.xml", "validation.json"):
            artifact = staging / name
            artifacts[name] = {
                "bytes": artifact.stat().st_size,
                "sha256": _sha256(artifact),
                "url": f"{public_base_url}/{name}" if public_base_url else None,
            }
        manifest = {
            "format": "m3u.guide-jellyfin-export",
            "version": 1,
            "profile": profile,
            "filters": {"group_prefixes": list(group_prefixes)},
            "provider": {"source_origin": stream_base, "active_origin": active_mirror or stream_base},
            "generated_at": generated_at,
            "artifacts": artifacts,
            "counts": {"m3u": m3u_counts, "xmltv": xml_counts},
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )

        for name in ("live.m3u8", "epg.xml", "validation.json", "manifest.json"):
            Path.replace(staging / name, export_dir / name)
        return manifest
    finally:
        shutil.rmtree(staging, ignore_errors=True)
