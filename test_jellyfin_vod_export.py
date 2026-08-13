from pathlib import Path
import tempfile
import unittest

from lxml import etree

from jellyfin_vod_export import generate_vod_fixture


class JellyfinVodExportTests(unittest.TestCase):
    def test_recovers_truncated_series_from_repeated_title(self):
        from jellyfin_vod_export import _episode_info
        from jellyfin_export import M3uEntry
        entry = M3uEntry(
            '#EXTINF:-1 group-title="NETFLIX  SERIES",and Boogaloo (2026) (CO) S01E01 - NF - Salcedo - S01E01 - Pilot',
            'https://example/series/1.mkv', {}
        )
        parsed = _episode_info(entry)
        self.assertEqual("Salcedo (2026) (CO)", parsed[0])
        self.assertIn("recovered", parsed[4])

    def test_generates_movies_and_native_show_layout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            playlist = root / "tv.m3u"
            playlist.write_text("""#EXTM3U
#EXTINF:-1 group-title="EN - NEW RELEASE" tvg-logo="https://example/movie.jpg",TOP - Film (2025)
http://m3u.futurepr0n.com/stream_proxy?url=http%3A//provider/movie/u/p/1.mkv
#EXTINF:-1 group-title="NETFLIX  SERIES",NF - Show (2024) (US) S01E02 - NF - Show (2024) (US) - S01E02 - Pilot
http://m3u.futurepr0n.com/stream_proxy?url=http%3A//provider/series/u/p/2.mkv
""", encoding="utf-8")
            output = root / "vod"

            counts = generate_vod_fixture(playlist, output, movie_limit=1, series_limit=1, episode_limit=1)

            self.assertEqual({"movies": 1, "series": 1, "episodes": 1}, counts)
            movie_stream = next((output / "Movies").rglob("*.strm"))
            self.assertTrue(movie_stream.read_text().startswith("https://m3u.futurepr0n.com/"))
            episode_nfo = next((output / "Shows").rglob("*S01E02*.nfo"))
            tree = etree.parse(str(episode_nfo))
            self.assertEqual("2", tree.xpath("string(/episodedetails/episode)"))
            self.assertEqual("Pilot", tree.xpath("string(/episodedetails/title)"))


if __name__ == "__main__":
    unittest.main()
