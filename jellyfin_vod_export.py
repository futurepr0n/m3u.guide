"""Build small native Jellyfin Movies/Shows libraries from provider VOD entries."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import shutil
import zipfile

from lxml import etree

from jellyfin_export import M3uEntry, _jellyfin_stream_url, iter_m3u


_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_YEAR = re.compile(r"\((19\d{2}|20\d{2})\)")
_EPISODE = re.compile(r"\bS(\d{1,2})E(\d{1,3})\b", re.IGNORECASE)
_SEASON_EPISODE_WORDS = re.compile(
    r"\b(?:season|saison|temporada|staffel)\s*(\d{1,2})\s*[-_. ]*"
    r"(?:episode|episodio|épisode|folge|ep)\s*(\d{1,3})\b", re.IGNORECASE
)
_EPISODE_WORD = re.compile(r"\b(?:episode|episodio|épisode|folge|ep)\s*(\d{1,4})\b", re.IGNORECASE)
_DATE_EPISODE = re.compile(r"\b(20\d{2})[-._ ](0?[1-9]|1[0-2])[-._ ](0?[1-9]|[12]\d|3[01])\b")
_PUNCTUATED_EPISODE = re.compile(r"\b(\d{1,2})\s*[xX._-]\s*(\d{1,3})\b")
_ABSOLUTE_EPISODE = re.compile(r"(?:^|\s)[#-]\s*(\d{1,4})\b")
_PREFIX = re.compile(r"^(?:TOP|NF)\s*[-:]\s*", re.IGNORECASE)
_SUSPICIOUS_SERIES = re.compile(r"^(?:and|or|the)\b", re.IGNORECASE)


def _display_name(entry: M3uEntry) -> str:
    return entry.extinf.rsplit(",", 1)[-1].strip()


def _safe(value: str) -> str:
    value = _INVALID_FILENAME.sub(" - ", value).strip().rstrip(".")
    return re.sub(r"\s+", " ", value)[:180] or "Untitled"


def _stable_id(entry: M3uEntry) -> str:
    return hashlib.sha256(entry.url.encode("utf-8")).hexdigest()[:24]


def _write_nfo(path: Path, root_name: str, values: dict[str, object]) -> None:
    root = etree.Element(root_name)
    for key, value in values.items():
        if value is None or value == "":
            continue
        child = etree.SubElement(root, key)
        child.text = str(value)
    path.write_bytes(etree.tostring(root, pretty_print=True, xml_declaration=True, encoding="utf-8"))


def _movie_info(entry: M3uEntry) -> tuple[str, int | None]:
    name = _PREFIX.sub("", _display_name(entry)).strip()
    match = _YEAR.search(name)
    return name, int(match.group(1)) if match else None


def _episode_info(entry: M3uEntry) -> tuple[str, int, int, str, str] | None:
    name = _display_name(entry)
    matches = list(_EPISODE.finditer(name))
    if not matches:
        candidates = [
            (_SEASON_EPISODE_WORDS.search(name), "season/episode words"),
            (_DATE_EPISODE.search(name), "dated episode"),
            (_PUNCTUATED_EPISODE.search(name), "punctuated season/episode"),
            (_EPISODE_WORD.search(name), "absolute episode word"),
            (_ABSOLUTE_EPISODE.search(name), "absolute episode number"),
        ]
        match, parse_note = next(((match, note) for match, note in candidates if match), (None, ""))
        if match is None:
            return None
        series = _PREFIX.sub("", name[:match.start()].strip(" -_.:|") )
        if not series:
            return None
        if parse_note == "dated episode":
            season = int(match.group(1))
            episode = (int(match.group(2)) * 100) + int(match.group(3))
        elif match.lastindex == 2:
            season, episode = int(match.group(1)), int(match.group(2))
        else:
            season, episode = 1, int(match.group(1))
        episode_title = name[match.end():].strip(" -_.:|") or f"Episode {episode}"
        return series, season, episode, episode_title, parse_note
    first, last = matches[0], matches[-1]
    series = _PREFIX.sub("", name[:first.start()].strip(" -"))
    parse_note = "primary episode marker"
    # Some providers prepend a truncated title, then repeat the real show name
    # before a second SxxExx marker. Prefer that repeated value when the first
    # title visibly begins mid-phrase, retaining useful year/country suffixes.
    if len(matches) > 1 and (_SUSPICIOUS_SERIES.search(series) or len(series) < 4):
        repeated = name[first.end():last.start()].strip(" -")
        repeated = _PREFIX.sub("", repeated).strip(" -")
        if repeated:
            suffix = " ".join(re.findall(r"\([^)]*\)", series))
            if suffix and suffix not in repeated:
                repeated = f"{repeated} {suffix}"
            series = repeated
            parse_note = "recovered from repeated title after truncated prefix"
    episode_title = name[last.end():].strip(" -") or f"Episode {int(last.group(2))}"
    episode_title = _PREFIX.sub("", episode_title)
    return series, int(last.group(1)), int(last.group(2)), episode_title, parse_note


def generate_vod_fixture(
    playlist: Path,
    destination: Path,
    *,
    movie_group: str = "EN - NEW RELEASE",
    series_group: str = "NETFLIX  SERIES",
    movie_limit: int = 25,
    series_limit: int = 3,
    episode_limit: int = 24,
    overrides_path: Path | None = None,
    package: bool = True,
) -> dict[str, int]:
    """Generate a bounded development VOD projection."""
    destination = Path(destination)
    if destination.exists():
        shutil.rmtree(destination)
    movies_root = destination / "Movies"
    shows_root = destination / "Shows"
    movies_root.mkdir(parents=True)
    shows_root.mkdir(parents=True)

    counts = Counter()
    overrides = {}
    if overrides_path and Path(overrides_path).exists():
        overrides = json.loads(Path(overrides_path).read_text(encoding="utf-8")).get("series_aliases", {})
    report: list[dict[str, object]] = []
    selected_series: list[str] = []
    for entry in iter_m3u(Path(playlist)):
        group = entry.attributes.get("group-title", "")
        if entry.content_kind == "movie" and group == movie_group and counts["movies"] < movie_limit:
            title, year = _movie_info(entry)
            folder = movies_root / _safe(title)
            folder.mkdir(exist_ok=True)
            stem = _safe(title)
            (folder / f"{stem}.strm").write_text(_jellyfin_stream_url(entry.url) + "\n", encoding="utf-8")
            _write_nfo(folder / "movie.nfo", "movie", {
                "title": title,
                "year": year,
                "genre": movie_group,
                "tag": movie_group,
                "uniqueid": _stable_id(entry),
                "thumb": entry.attributes.get("tvg-logo"),
            })
            counts["movies"] += 1
        elif entry.content_kind == "series" and group == series_group and counts["episodes"] < episode_limit:
            info = _episode_info(entry)
            if info is None:
                counts["unparsed_episodes"] += 1
                continue
            series, season, episode, episode_title, parse_note = info
            parsed_series = series
            series = overrides.get(series, series)
            if series != parsed_series:
                parse_note = "series_aliases override"
                counts["overrides_applied"] += 1
            report.append({
                "source_title": _display_name(entry), "series": series,
                "season": season, "episode": episode,
                "episode_title": episode_title, "parse_note": parse_note,
            })
            if series not in selected_series:
                if len(selected_series) >= series_limit:
                    continue
                selected_series.append(series)
                show = shows_root / _safe(series)
                show.mkdir(exist_ok=True)
                _write_nfo(show / "tvshow.nfo", "tvshow", {
                    "title": series,
                    "genre": series_group,
                    "tag": series_group,
                    "uniqueid": hashlib.sha256(series.encode("utf-8")).hexdigest()[:24],
                })
                counts["series"] += 1
            if series not in selected_series:
                continue
            season_folder = shows_root / _safe(series) / f"Season {season:02d}"
            season_folder.mkdir(exist_ok=True)
            stem = _safe(f"{series} S{season:02d}E{episode:02d} - {episode_title}")
            (season_folder / f"{stem}.strm").write_text(_jellyfin_stream_url(entry.url) + "\n", encoding="utf-8")
            _write_nfo(season_folder / f"{stem}.nfo", "episodedetails", {
                "title": episode_title,
                "showtitle": series,
                "season": season,
                "episode": episode,
                "genre": series_group,
                "tag": series_group,
                "uniqueid": _stable_id(entry),
                "thumb": entry.attributes.get("tvg-logo"),
            })
            counts["episodes"] += 1

        if counts["movies"] >= movie_limit and counts["episodes"] >= episode_limit:
            break
    (destination / "parse-report.json").write_text(
        json.dumps({"episodes": report}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    if package:
        archive = destination.with_suffix(".zip")
        if archive.exists():
            archive.unlink()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            for artifact in destination.rglob("*"):
                if artifact.is_file():
                    bundle.write(artifact, artifact.relative_to(destination))
    return dict(counts)
