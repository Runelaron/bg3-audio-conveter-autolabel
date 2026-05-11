from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from converters import create_bank_folders


class ConvertersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.banks = self.tmp_path / "banks"
        self.sounds = self.tmp_path / "sounds"
        shutil.copytree(FIXTURES / "banks", self.banks)
        shutil.copytree(FIXTURES / "group_flat", self.sounds)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_create_bank_folders_moves_known_ids(self) -> None:
        create_bank_folders(self.banks, self.sounds)

        target = self.sounds / "sample.bnk"
        self.assertTrue((target / "100.wem.wav").exists())
        self.assertTrue((target / "300.wem.wav").exists())
        self.assertTrue((self.sounds / "999.wem.wav").exists())


if __name__ == "__main__":
    unittest.main()
