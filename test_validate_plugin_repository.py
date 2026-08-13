import json
import tempfile
import unittest
import zipfile
from pathlib import Path
import hashlib

from validate_plugin_repository import validate


class ValidatePluginRepositoryTests(unittest.TestCase):
    def test_accepts_complete_release_and_detects_checksum_damage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "m3u-logo.jpg").write_bytes(b"image")
            package = root / "Jellyfin.Plugin.M3uGuide_1.2.3.4.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("Jellyfin.Plugin.M3uGuide.dll", b"assembly")
                archive.writestr("m3u-logo.jpg", b"image")
                archive.writestr("meta.json", json.dumps({"version": "1.2.3.4", "imagePath": "m3u-logo.jpg"}))
            checksum = hashlib.md5(package.read_bytes()).hexdigest().upper()
            manifest = [{"imageUrl": "https://example/m3u-logo.jpg", "versions": [{"version": "1.2.3.4", "checksum": checksum}]}]
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

            self.assertEqual([], validate(root))
            package.write_bytes(package.read_bytes() + b"damage")
            self.assertIn("1.2.3.4: checksum mismatch", validate(root))


if __name__ == "__main__":
    unittest.main()
