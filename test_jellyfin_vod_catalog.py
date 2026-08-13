from pathlib import Path
import tempfile
import unittest

from jellyfin_vod_catalog import generate_vod_catalog, read_catalog_page


class JellyfinVodCatalogTests(unittest.TestCase):
    def test_generates_full_paginated_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            playlist = root / "tv.m3u"
            playlist.write_text("""#EXTM3U
#EXTINF:-1 group-title="MOVIES",Film (2025)
https://example/movie/u/p/1.mkv
#EXTINF:-1 group-title="SHOWS",Show S01E01 - Pilot
https://example/series/u/p/2.mkv
#EXTINF:-1 group-title="SHOWS",Show S01E02 - Second
https://example/series/u/p/3.mkv
""", encoding="utf-8")
            profile = {
                "name": "default", "include_movies": True, "include_series": True,
                "movie_groups": [], "series_groups": [], "remove_missing_vod": True,
            }
            manifest = generate_vod_catalog(playlist, root / "export", profile)
            self.assertEqual(2, manifest["counts"]["selected_series_entries"])
            self.assertEqual(2, manifest["counts"]["parsed_series_entries"])
            self.assertEqual(1, manifest["counts"]["movies"])
            self.assertEqual(1, manifest["counts"]["series"])
            self.assertEqual(1, manifest["counts"]["seasons"])
            self.assertEqual(2, manifest["counts"]["episodes"])
            records = []
            cursor = 0
            while cursor is not None:
                page, cursor = read_catalog_page(root / "export" / "vod.catalog.jsonl", cursor, 2)
                records.extend(page)
            self.assertEqual(5, len(records))
            self.assertEqual({"movie", "series", "episode"}, {x["kind"] for x in records})
            season = next(item for item in records if item["relative_path"].endswith("season.nfo"))
            self.assertIn("<seasonnumber>1</seasonnumber>", season["content"])


if __name__ == "__main__":
    unittest.main()
