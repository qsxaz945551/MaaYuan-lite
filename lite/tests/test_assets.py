from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OCR_DIR = ROOT / "assets" / "resource" / "base" / "model" / "ocr"


class RuntimeAssetTest(unittest.TestCase):
    def test_ocr_models_are_present_and_not_placeholders(self):
        for name in ("det.onnx", "rec.onnx", "keys.txt"):
            path = OCR_DIR / name
            with self.subTest(name=name):
                self.assertTrue(path.is_file(), f"missing OCR asset: {path}")
                self.assertGreater(path.stat().st_size, 1024)


if __name__ == "__main__":
    unittest.main()
