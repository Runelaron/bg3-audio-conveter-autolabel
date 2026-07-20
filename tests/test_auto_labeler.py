from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import auto_labeler


def _snapshot(root: Path) -> dict[str, str]:
    files = [path for path in root.rglob("*") if path.is_file()]
    snap: dict[str, str] = {}
    for file_path in sorted(files, key=lambda p: p.as_posix()):
        rel = file_path.relative_to(root).as_posix()
        snap[rel] = hashlib.sha256(file_path.read_bytes()).hexdigest()
    return snap


def _write_wiki(md: Path, rows: list[tuple[str, str]]) -> None:
    lines = [
        "# Sample",
        "| Index | Name | WEM ID |",
        "| :---: | --- | --- |",
    ]
    for index, (name, sid_text) in enumerate(rows, 1):
        lines.append(f"| {index} | {name} | {sid_text} |")
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")


class AutoLabelerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.src = self.tmp_path / "src"
        self.wiki = self.tmp_path / "wiki"
        self.dst = self.tmp_path / "out"
        shutil.copytree(FIXTURES / "src", self.src)
        shutil.copytree(FIXTURES / "wiki", self.wiki)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_duplicate_id_is_preserved_with_copy(self) -> None:
        report = auto_labeler.categorise_wems(self.wiki, self.src, self.dst)

        self.assertEqual(report["missing_sources"], 1)
        self.assertTrue((self.dst / "sample" / "Attack_Primary.wav").exists())
        self.assertTrue((self.dst / "sample" / "DuplicateID.wav").exists())
        self.assertTrue((self.dst / "sample" / "Combo_Name" / "1.wav").exists())
        self.assertTrue((self.dst / "sample" / "Combo_Name" / "2.wav").exists())
        self.assertTrue((self.dst / "sample" / "CON_.wav").exists())
        self.assertTrue((self.dst / "sample" / "TrailingName.wav").exists())

    def test_second_run_is_idempotent(self) -> None:
        auto_labeler.categorise_wems(self.wiki, self.src, self.dst)
        first = _snapshot(self.dst)

        auto_labeler.categorise_wems(self.wiki, self.src, self.dst)
        second = _snapshot(self.dst)

        self.assertEqual(first, second)

    def test_operation_callback_reports_every_task(self) -> None:
        operations: list[dict[str, object]] = []

        report = auto_labeler.categorise_wems(
            self.wiki,
            self.src,
            self.dst,
            dry_run=True,
            on_operation=operations.append,
        )

        self.assertEqual(len(operations), report["total_tasks"])
        statuses = [operation["status"] for operation in operations]
        self.assertEqual(statuses.count("planned"), 6)
        self.assertEqual(statuses.count("missing_source"), 1)
        self.assertFalse(self.dst.exists())

    def test_windows_unsafe_names_are_sanitized(self) -> None:
        auto_labeler.categorise_wems(self.wiki, self.src, self.dst)
        forbidden = set('<>:"/\\|?*')
        for path in self.dst.rglob("*"):
            name = path.name
            self.assertFalse(any(ch in forbidden for ch in name))
            if path.is_file():
                self.assertNotEqual(path.stem.upper(), "CON")

    def test_source_index_built_once_per_run(self) -> None:
        with mock.patch(
            "auto_labeler.build_source_index",
            wraps=auto_labeler.build_source_index,
        ) as wrapped:
            auto_labeler.categorise_wems(self.wiki, self.src, self.dst)
            self.assertEqual(wrapped.call_count, 1)

    def test_bank_hint_prefers_matching_bank_candidate(self) -> None:
        src = self.tmp_path / "banked-src"
        wiki = self.tmp_path / "banked-wiki"
        dst = self.tmp_path / "banked-out"
        (src / "bank_a.bnk").mkdir(parents=True)
        (src / "bank_b.bnk").mkdir(parents=True)
        wiki.mkdir(parents=True)
        (src / "bank_a.bnk" / "100.wem.wav").write_bytes(b"BANK-A\n")
        (src / "bank_b.bnk" / "100.wem.wav").write_bytes(b"BANK-B\n")
        wiki_md = wiki / "Sample-&-bank_a.bnk.md"
        _write_wiki(wiki_md, [("Preferred", "100")])

        report = auto_labeler.categorise_wems(wiki, src, dst)

        target = dst / auto_labeler._safe(wiki_md.stem) / "Preferred.wav"
        self.assertTrue(target.exists())
        self.assertEqual(target.read_bytes(), b"BANK-A\n")
        self.assertEqual(report["resolved_by_bank"], 1)
        self.assertEqual(report["ambiguous_sources"], 0)
        self.assertEqual(report["unused_source_files"], 1)

    def test_ambiguous_global_candidates_are_reported(self) -> None:
        src = self.tmp_path / "ambiguous-src"
        wiki = self.tmp_path / "ambiguous-wiki"
        dst = self.tmp_path / "ambiguous-out"
        (src / "bank_a.bnk").mkdir(parents=True)
        (src / "bank_b.bnk").mkdir(parents=True)
        wiki.mkdir(parents=True)
        (src / "bank_a.bnk" / "100.wem.wav").write_bytes(b"A\n")
        (src / "bank_b.bnk" / "100.wem.wav").write_bytes(b"B\n")
        _write_wiki(wiki / "Sample.md", [("Ambiguous", "100")])

        report = auto_labeler.categorise_wems(wiki, src, dst)

        self.assertEqual(report["ambiguous_sources"], 1)
        self.assertEqual(report["labeled"], 0)
        self.assertFalse(any(dst.rglob("*.wav")))

    def test_byte_identical_duplicates_are_treated_as_one_source(self) -> None:
        src = self.tmp_path / "identical-src"
        wiki = self.tmp_path / "identical-wiki"
        dst = self.tmp_path / "identical-out"
        (src / "bank_a.bnk").mkdir(parents=True)
        (src / "bank_b.bnk").mkdir(parents=True)
        wiki.mkdir(parents=True)
        for bank in ("bank_a.bnk", "bank_b.bnk"):
            (src / bank / "100.wem.wav").write_bytes(b"SAME\n")
        _write_wiki(wiki / "Sample.md", [("UniqueEnough", "100")])

        report = auto_labeler.categorise_wems(wiki, src, dst)

        self.assertEqual(report["ambiguous_sources"], 0)
        self.assertEqual(report["resolved_by_global_unique"], 1)
        self.assertTrue((dst / "Sample" / "UniqueEnough.wav").exists())
        self.assertEqual(report["unused_source_files"], 1)

    def test_destination_conflicts_are_suffixed(self) -> None:
        src = self.tmp_path / "conflict-src"
        wiki = self.tmp_path / "conflict-wiki"
        dst = self.tmp_path / "conflict-out"
        src.mkdir(parents=True)
        wiki.mkdir(parents=True)
        (src / "100.wem.wav").write_bytes(b"FIRST\n")
        (src / "101.wem.wav").write_bytes(b"SECOND\n")
        _write_wiki(
            wiki / "Sample.md",
            [("A/B", "100"), ("A?B", "101")],
        )

        report = auto_labeler.categorise_wems(wiki, src, dst)

        self.assertEqual(report["destination_conflicts"], 1)
        self.assertTrue((dst / "Sample" / "A_B.wav").exists())
        self.assertTrue((dst / "Sample" / "A_B_2.wav").exists())

    def test_cli_dry_run_writes_report(self) -> None:
        report_path = self.tmp_path / "report.json"
        result = subprocess.run(
            [
                sys.executable,
                "auto_labeler.py",
                "--src",
                str(self.src),
                "--dst",
                str(self.dst),
                "--wiki",
                str(self.wiki),
                "--dry-run",
                "--report",
                str(report_path),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertTrue(report_path.exists())
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertTrue(report["dry_run"])
        self.assertIn("labeled", report)
        self.assertIn("ambiguous_sources", report)
        self.assertIn("unused_source_files", report)
        self.assertFalse(any(self.dst.rglob("*.wav")))


if __name__ == "__main__":
    unittest.main()
