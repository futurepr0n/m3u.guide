import json
from pathlib import Path
import re
import tempfile
import unittest

from lxml import etree

from jellyfin_export import generate_jellyfin_export, iter_m3u


def _write_fixture(root: Path):
    (root / "tv.m3u").write_text(
        """#EXTM3U
#EXTINF:-1 tvg-id="live.one" tvg-name="One" tvg-logo="one.png" group-title="News",One
http://provider/live/u/p/1
#EXTINF:-1 tvg-id="" tvg-name="Movie" tvg-logo="movie.png" group-title="Movies",Movie
http://provider/movie/u/p/2
#EXTINF:-1 tvg-id="" tvg-name="Show S01E01" tvg-logo="show.png" group-title="Shows",Show S01E01
https://m3u.guide/stream_proxy?url=http%3A%2F%2Fprovider%2Fseries%2Fu%2Fp%2F3
#EXTINF:-1 tvg-id="missing" tvg-name="Two" tvg-logo="two.png" group-title="News",Two
http://m3u.futurepr0n.com/stream_proxy?url=http%3A//provider/live/u/p/4
""",
        encoding="utf-8",
    )
    (root / "epg.xml").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<tv>
  <channel id="LIVE.ONE"><display-name>One</display-name></channel>
  <channel id="LIVE.ONE"><display-name>Duplicate</display-name></channel>
  <programme channel="LIVE.ONE" start="20260812000000 +0000" stop="20260812010000 +0000"><title>News</title></programme>
</tv>
""",
        encoding="utf-8",
    )


class JellyfinExportTests(unittest.TestCase):
    def test_live_channels_without_epg_receive_stable_ids_and_categorized_programmes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tv.m3u").write_text(
                '#EXTM3U\n#EXTINF:-1 tvg-id="" group-title="US| SPORTS PPV",UFC Event\n'
                'http://provider/live/user/pass/42.ts\n',
                encoding="utf-8",
            )
            (root / "epg.xml").write_text('<?xml version="1.0"?><tv/>', encoding="utf-8")

            generate_jellyfin_export(root)
            live = (root / "exports/jellyfin/default/live.m3u8").read_text(encoding="utf-8")
            tree = etree.parse(str(root / "exports/jellyfin/default/epg.xml"))

            fallback_id = re.search(r'tvg-id="(m3uguide\.[0-9a-f]{24})"', live).group(1)
            self.assertEqual(fallback_id, tree.xpath("string(/tv/channel/@id)"))
            self.assertEqual(fallback_id, tree.xpath("string(/tv/programme/@channel)"))
            self.assertIn("Sports", tree.xpath("/tv/programme/category/text()"))

    def test_generates_jellyfin_live_projection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_fixture(root)
            manifest = generate_jellyfin_export(root, "https://example/jellyfin")
            output = root / "exports" / "jellyfin" / "default"

            entries = list(iter_m3u(output / "live.m3u8"))
            self.assertEqual(2, len(entries))
            self.assertTrue(all(entry.content_kind == "live" for entry in entries))
            self.assertEqual("1", entries[0].attributes["tvg-chno"])
            self.assertEqual("2", entries[1].attributes["tvg-chno"])
            self.assertTrue(all("x-m3uguide-id" in entry.attributes for entry in entries))
            self.assertEqual(
                "https://m3u.futurepr0n.com/stream_proxy?url=http%3A//provider/live/u/p/4",
                entries[1].url,
            )

            tree = etree.parse(str(output / "epg.xml"))
            self.assertEqual(2, tree.xpath("count(/tv/channel)"))
            self.assertEqual(2, tree.xpath("count(/tv/programme)"))
            self.assertEqual("live.one", tree.xpath("string(/tv/channel[@id='live.one']/@id)"))
            self.assertEqual("live.one", tree.xpath("string(/tv/programme[@channel='live.one']/@channel)"))
            self.assertEqual(
                ["News"], tree.xpath("/tv/programme[@channel='live.one']/category/text()")
            )

            validation = json.loads((output / "validation.json").read_text())
            self.assertEqual(1, validation["m3u"]["source_movie"])
            self.assertEqual(1, validation["m3u"]["source_series"])
            self.assertEqual(1, validation["xmltv"]["duplicate_channels_removed"])
            self.assertEqual(1, validation["xmltv"]["channel_ids_missing_from_xmltv"])
            self.assertEqual(1, validation["xmltv"]["categories_added"])
            self.assertTrue(manifest["artifacts"]["live.m3u8"]["url"].endswith("/live.m3u8"))

    def test_prefers_edited_playlist(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_fixture(root)
            (root / "tv_edited.m3u").write_text(
                """#EXTM3U
#EXTINF:-1 tvg-id="live.one" tvg-name="Renamed" group-title="Favorites",Renamed
http://provider/live/u/p/1
""",
                encoding="utf-8",
            )

            generate_jellyfin_export(root)
            output = root / "exports" / "jellyfin" / "default"
            entries = list(iter_m3u(output / "live.m3u8"))
            self.assertEqual(1, len(entries))
            self.assertEqual("Favorites", entries[0].attributes["group-title"])
            self.assertIn("Renamed", entries[0].extinf)

    def test_group_prefix_profile_exports_matching_first_facet(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_fixture(root)
            (root / "tv.m3u").write_text(
                """#EXTM3U
#EXTINF:-1 tvg-id="ca.news" group-title="CA| NEWS EN",Canadian News
http://provider/live/ca
#EXTINF:-1 tvg-id="us.news" group-title="US| NEWS",US News
http://provider/live/us
""",
                encoding="utf-8",
            )
            (root / "epg.xml").write_text(
                """<tv>
<channel id="ca.news"><display-name>Canadian News</display-name></channel>
<channel id="us.news"><display-name>US News</display-name></channel>
<programme channel="ca.news" start="20260812000000 +0000" stop="20260812010000 +0000"><title>CA</title></programme>
<programme channel="us.news" start="20260812000000 +0000" stop="20260812010000 +0000"><title>US</title></programme>
</tv>""",
                encoding="utf-8",
            )

            manifest = generate_jellyfin_export(
                root, profile="canada", group_prefixes=("CA",)
            )
            output = root / "exports" / "jellyfin" / "canada"
            entries = list(iter_m3u(output / "live.m3u8"))

            self.assertEqual(1, len(entries))
            self.assertEqual("CA| NEWS EN", entries[0].attributes["group-title"])
            self.assertEqual(1, manifest["counts"]["m3u"]["excluded_by_group"])
            self.assertEqual(["CA"], manifest["filters"]["group_prefixes"])
            tree = etree.parse(str(output / "epg.xml"))
            self.assertEqual(["ca.news"], tree.xpath("/tv/channel/@id"))

    def test_canadian_provider_groups_receive_canonical_categories(self):
        from jellyfin_export import _group_categories

        self.assertIn("Sports", _group_categories("CA| TSN+ PPV"))
        self.assertIn("Sports", _group_categories("CA| DAZN PPV"))
        self.assertIn("Sports", _group_categories("CA| WHL PPV"))
        self.assertIn("Sports", _group_categories("US| UFC PPV"))
        self.assertIn("Sports", _group_categories("UK| MATCHROOM BOXING PPV"))
        self.assertNotIn("Sports", _group_categories("NETFLIX PPV"))
        self.assertIn("Kids", _group_categories("CA| KIDS FR"))
        self.assertIn("Movie", _group_categories("CA| CINEMA EN"))
        self.assertIn("News", _group_categories("CA| NEWS EN"))
        self.assertNotIn("News", _group_categories("CA| DOCUMENTARY EN"))


if __name__ == "__main__":
    unittest.main()
