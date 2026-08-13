from pathlib import Path
import json
import tempfile
import unittest

from jellyfin_export import M3uEntry
from jellyfin_vod_catalog import generate_vod_catalog
from jellyfin_vod_export import _episode_info, _stable_id


def entry(title: str, url: str = "https://example/series/u/p/1.mkv") -> M3uEntry:
    return M3uEntry(f'#EXTINF:-1 group-title="Shows",{title}', url, {"group-title": "Shows"})


class SeriesParsingTests(unittest.TestCase):
    def test_common_episode_naming_families(self):
        cases = {
            "Show S02E011 - Title": ("Show", 2, 11, "Title"),
            "Show Season 3 Episode 7 - Title": ("Show", 3, 7, "Title"),
            "Show Saison 4 Épisode 8 - Titre": ("Show", 4, 8, "Titre"),
            "Show 5x09 - Title": ("Show", 5, 9, "Title"),
            "Daily Show 2026-08-12 - News": ("Daily Show", 2026, 812, "News"),
            "Anime Episode 127 - Title": ("Anime", 1, 127, "Title"),
            "Anime # 128 - Title": ("Anime", 1, 128, "Title"),
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                parsed = _episode_info(entry(title))
                self.assertIsNotNone(parsed)
                self.assertEqual(expected, parsed[:4])

    def test_failures_are_diagnostic_and_stable_id_override_materializes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_entry = entry("Mystery installment", "https://example/series/u/p/99.mkv")
            playlist = root / "tv.m3u"
            playlist.write_text("#EXTM3U\n" + source_entry.extinf + "\n" + source_entry.url + "\n", encoding="utf-8")
            profile = {"name": "default", "include_movies": True, "include_series": True,
                       "movie_groups": [], "series_groups": [], "remove_missing_vod": True}
            output = root / "export"
            first = generate_vod_catalog(playlist, output, profile)
            self.assertEqual(1, first["counts"]["unparsed_episodes"])
            diagnostic = json.loads((output / "vod.parse-diagnostics.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(_stable_id(source_entry), diagnostic["id"])
            self.assertEqual("Mystery installment", diagnostic["original_title"])
            self.assertEqual("no supported episode marker", diagnostic["reason"])

            overrides = root / "vod-overrides.json"
            overrides.write_text(json.dumps({"version": 1, "items": {
                diagnostic["id"]: {"series": "Mystery Show", "season": 2, "episode": 5, "episode_title": "Solved"}
            }}), encoding="utf-8")
            second = generate_vod_catalog(playlist, output, profile, overrides_path=overrides)
            self.assertEqual(1, second["counts"]["overrides_applied"])
            records = [json.loads(line) for line in (output / "vod.catalog.jsonl").read_text(encoding="utf-8").splitlines()]
            episode_record = next(item for item in records if item["kind"] == "episode")
            self.assertIn("Season 02", episode_record["relative_path"])
            self.assertIn("<title>Solved</title>", episode_record["nfo"])
            self.assertEqual("", (output / "vod.parse-diagnostics.jsonl").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
