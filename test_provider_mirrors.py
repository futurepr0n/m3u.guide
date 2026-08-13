from pathlib import Path
import json
import tempfile
import unittest

from jellyfin_export import generate_jellyfin_export
from jellyfin_vod_catalog import generate_vod_catalog
from provider_mirrors import normalize_mirrors, normalize_origin, rewrite_provider_url
from provider_health import _classification


class ProviderMirrorTests(unittest.TestCase):
    def test_health_failure_classifications(self):
        self.assertEqual((False, "cloudflare_origin_error"), _classification(520, b"", False))
        self.assertEqual((False, "throttled"), _classification(429, b"", False))
        self.assertEqual((False, "authentication_failed"), _classification(401, b"", False))
        self.assertEqual((False, "empty_catalog"), _classification(200, b"[]", True))
        self.assertEqual((True, "healthy"), _classification(200, b"[{\"id\":1}]", True))

    def test_validates_and_rewrites_direct_and_proxy_urls(self):
        self.assertEqual("http://mirror.example:8080", normalize_origin("http://mirror.example:8080/"))
        self.assertEqual(
            ["https://one.example", "https://two.example"],
            normalize_mirrors(["https://one.example", "https://two.example/", "https://ONE.example"]),
        )
        direct = "http://source.example:80/live/u/p/1.ts"
        self.assertEqual(
            "https://mirror.example:443/live/u/p/1.ts",
            rewrite_provider_url(direct, "http://source.example:80", "https://mirror.example:443"),
        )
        proxy = "https://guide.example/stream_proxy?url=http%3A//source.example%3A80/live/u/p/1.ts"
        self.assertIn(
            "https%3A//mirror.example%3A443/live/u/p/1.ts",
            rewrite_provider_url(proxy, "http://source.example:80", "https://mirror.example:443"),
        )

    def test_rejects_mirror_paths_and_credentials(self):
        for value in ("https://user:pass@example.com", "https://example.com/path", "ftp://example.com"):
            with self.assertRaises(ValueError):
                normalize_origin(value)

    def test_jellyfin_exports_use_mirror_without_changing_stable_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.joinpath("tv.m3u").write_text(
                '#EXTM3U\n#EXTINF:-1 tvg-id="live" group-title="News",News\n'
                'http://source.example/live/u/p/1.ts\n'
                '#EXTINF:-1 group-title="Movies",Film (2025)\n'
                'http://source.example/movie/u/p/2.mkv\n',
                encoding="utf-8",
            )
            root.joinpath("epg.xml").write_text('<tv><channel id="live"/></tv>', encoding="utf-8")
            manifest = generate_jellyfin_export(
                root, stream_base="http://source.example", active_mirror="https://mirror.example"
            )
            live = root.joinpath("exports/jellyfin/default/live.m3u8").read_text(encoding="utf-8")
            self.assertIn("https://mirror.example/live/u/p/1.ts", live)
            self.assertNotIn("http://source.example/live", live)
            self.assertEqual("https://mirror.example", manifest["provider"]["active_origin"])

            profile = {"name": "default", "include_movies": True, "include_series": True,
                       "movie_groups": [], "series_groups": [], "remove_missing_vod": True}
            generate_vod_catalog(
                root / "tv.m3u", root / "vod", profile,
                stream_base="http://source.example", active_mirror="https://mirror.example",
            )
            record = json.loads((root / "vod/vod.catalog.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual("https://mirror.example/movie/u/p/2.mkv", record["stream_url"])


if __name__ == "__main__":
    unittest.main()
