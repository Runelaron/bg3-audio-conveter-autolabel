from __future__ import annotations

import os
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _write_wiki(md: Path, rows: list[tuple[str, str]]) -> None:
    lines = [
        "# Sample",
        "| Index | Name | WEM ID |",
        "| :---: | --- | --- |",
    ]
    for index, (name, sid_text) in enumerate(rows, 1):
        lines.append(f"| {index} | {name} | {sid_text} |")
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")


class MainTests(unittest.TestCase):
    def _run_main(self, extra_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update(extra_env)
        return subprocess.run(
            [sys.executable, "main.py"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def _prepare_label_only_fixture(self, tmp: str) -> tuple[Path, Path, Path]:
        tmp_path = Path(tmp)
        converted = tmp_path / "converted"
        labeled = tmp_path / "labeled"
        wiki = tmp_path / "wiki"

        for root_name, payload in (("Shared", b"SHARED\n"), ("SharedDev", b"DEV\n")):
            bank_dir = converted / root_name / "sample.bnk"
            bank_dir.mkdir(parents=True, exist_ok=True)
            (bank_dir / "100.wem.wav").write_bytes(payload)

        wiki.mkdir(parents=True, exist_ok=True)
        _write_wiki(wiki / "Sample-&-sample.bnk.md", [("Attack", "100")])
        return converted, labeled, wiki

    def test_sort_flag_off_does_not_require_sids_wiki(self) -> None:
        result = self._run_main(
            {
                "BG3_CONVERT": "0",
                "BG3_DECODE_BANKS": "0",
                "BG3_GROUP_BY_BANK": "0",
                "BG3_SORT_BY_SID": "0",
            }
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Done", result.stdout)

    def test_missing_source_path_fails_fast(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "does-not-exist"
            converted = Path(tmp) / "converted"

            result = self._run_main(
                {
                    "UNPACKED_DATA": str(missing),
                    "AUDIO_CONVERTED": str(converted),
                    "BG3_CONVERT": "1",
                    "BG3_DECODE_BANKS": "0",
                    "BG3_GROUP_BY_BANK": "0",
                    "BG3_SORT_BY_SID": "0",
                }
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[path-error]", result.stderr)

    def test_sort_enabled_requires_sids_wiki(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            converted = Path(tmp) / "converted"
            converted.mkdir(parents=True, exist_ok=True)

            result = self._run_main(
                {
                    "AUDIO_CONVERTED": str(converted),
                    "BG3_CONVERT": "0",
                    "BG3_DECODE_BANKS": "0",
                    "BG3_GROUP_BY_BANK": "0",
                    "BG3_SORT_BY_SID": "1",
                    "SIDS_WIKI": "",
                }
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[env-error]", result.stderr)

    def test_sort_validation_happens_before_convert_path_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing_unpacked = Path(tmp) / "does-not-exist"
            converted = Path(tmp) / "converted"

            result = self._run_main(
                {
                    "UNPACKED_DATA": str(missing_unpacked),
                    "AUDIO_CONVERTED": str(converted),
                    "BG3_CONVERT": "1",
                    "BG3_DECODE_BANKS": "0",
                    "BG3_GROUP_BY_BANK": "0",
                    "BG3_SORT_BY_SID": "1",
                    "SIDS_WIKI": "",
                }
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[env-error]", result.stderr)
        self.assertNotIn("[path-error]", result.stderr)

    def test_label_only_run_writes_labeled_output_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            converted, labeled, wiki = self._prepare_label_only_fixture(tmp)
            report_path = Path(tmp) / "label-report.json"

            result = self._run_main(
                {
                    "AUDIO_CONVERTED": str(converted),
                    "AUDIO_LABELED": str(labeled),
                    "SIDS_WIKI": str(wiki),
                    "BG3_CONVERT": "0",
                    "BG3_DECODE_BANKS": "0",
                    "BG3_GROUP_BY_BANK": "0",
                    "BG3_SORT_BY_SID": "1",
                    "BG3_LABEL_REPORT": str(report_path),
                }
            )

            shared_target = labeled / "Shared" / "Sample-_-sample.bnk" / "Attack.wav"
            shared_dev_target = (
                labeled / "SharedDev" / "Sample-_-sample.bnk" / "Attack.wav"
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertTrue(shared_target.exists())
            self.assertTrue(shared_dev_target.exists())
            self.assertEqual(shared_target.read_bytes(), b"SHARED\n")
            self.assertEqual(shared_dev_target.read_bytes(), b"DEV\n")
            self.assertTrue(report_path.exists())

            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["labeled"], 2)
            self.assertEqual(report["summary"]["missing_sources"], 0)
            self.assertEqual(report["summary"]["missing_source_roots"], 0)
            self.assertEqual(report["roots"]["Shared"]["resolved_by_bank"], 1)
            self.assertEqual(report["roots"]["SharedDev"]["resolved_by_bank"], 1)

    def test_best_effort_sort_reports_missing_root_without_failing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            converted, labeled, wiki = self._prepare_label_only_fixture(tmp)
            shutil.rmtree(converted / "SharedDev")
            report_path = Path(tmp) / "label-report.json"

            result = self._run_main(
                {
                    "AUDIO_CONVERTED": str(converted),
                    "AUDIO_LABELED": str(labeled),
                    "SIDS_WIKI": str(wiki),
                    "BG3_CONVERT": "0",
                    "BG3_DECODE_BANKS": "0",
                    "BG3_GROUP_BY_BANK": "0",
                    "BG3_SORT_BY_SID": "1",
                    "BG3_LABEL_REPORT": str(report_path),
                }
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["missing_source_roots"], 1)
            self.assertTrue(report["roots"]["SharedDev"]["source_root_missing"])
            self.assertIn("source root missing", result.stdout)

    def test_strict_sort_fails_on_missing_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            converted, labeled, wiki = self._prepare_label_only_fixture(tmp)
            shutil.rmtree(converted / "SharedDev")
            report_path = Path(tmp) / "label-report.json"

            result = self._run_main(
                {
                    "AUDIO_CONVERTED": str(converted),
                    "AUDIO_LABELED": str(labeled),
                    "SIDS_WIKI": str(wiki),
                    "BG3_CONVERT": "0",
                    "BG3_DECODE_BANKS": "0",
                    "BG3_GROUP_BY_BANK": "0",
                    "BG3_SORT_BY_SID": "1",
                    "BG3_LABEL_STRICT": "1",
                    "BG3_LABEL_REPORT": str(report_path),
                }
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Strict label audit failed.", result.stdout)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertTrue(report["summary"]["has_unresolved_labels"])
            self.assertEqual(report["summary"]["missing_source_roots"], 1)


if __name__ == "__main__":
    unittest.main()
