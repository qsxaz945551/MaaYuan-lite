"""The landscape check exists because a rotated emulator fails every task.

MaaYuan's ROIs are written for a portrait 720x1280 screen. Running against
1280x720 produces dozens of "roi is out of range" lines and no obvious cause,
so the service reads the screenshot header and says it once, clearly.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lite.run_service import _png_size


class PngSizeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write(self, name: str, size: tuple[int, int]) -> Path:
        from PIL import Image

        path = self.root / name
        Image.new("RGB", size, (30, 30, 30)).save(path)
        return path

    def test_portrait(self) -> None:
        self.assertEqual(_png_size(self._write("p.png", (720, 1280))), (720, 1280))

    def test_landscape(self) -> None:
        self.assertEqual(_png_size(self._write("l.png", (1280, 720))), (1280, 720))

    def test_missing_file(self) -> None:
        self.assertIsNone(_png_size(self.root / "nope.png"))

    def test_not_a_png(self) -> None:
        path = self.root / "x.png"
        path.write_bytes(b"not an image at all")
        self.assertIsNone(_png_size(path))


if __name__ == "__main__":
    unittest.main()
