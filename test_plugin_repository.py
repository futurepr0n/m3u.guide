import json
import tempfile
import unittest
from pathlib import Path

from plugin_repository import build_manifest, package_filename


class PluginRepositoryTests(unittest.TestCase):
    def test_rewrites_package_urls_to_public_origin(self):
        manifest = [{"name": "m3u.guide", "versions": [{
            "version": "0.12.0.0",
            "sourceUrl": "http://127.0.0.1:4444/old.zip",
        }]}]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            result = build_manifest(path, "https://m3u.example/", "/api/jellyfin/plugin-repository/packages/")

        self.assertEqual(
            result[0]["versions"][0]["sourceUrl"],
            "https://m3u.example/api/jellyfin/plugin-repository/packages/Jellyfin.Plugin.M3uGuide_0.12.0.0.zip",
        )
        self.assertEqual(
            result[0]["imageUrl"],
            "https://m3u.example/api/jellyfin/plugin-repository/packages/m3u-logo.jpg",
        )

    def test_rejects_non_version_package_names(self):
        with self.assertRaises(ValueError):
            package_filename("../../secret")


if __name__ == "__main__":
    unittest.main()
