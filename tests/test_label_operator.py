from __future__ import annotations

from contextlib import ExitStack
import hashlib
import os
import shutil
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

from scripts import bg3_label_operator as operator


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
TEST_SHA = "a" * 40


def _snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file()
    }


class LabelOperatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name) / "repo"
        self.repo.mkdir()
        shutil.copy2(ROOT / "auto_labeler.py", self.repo / "auto_labeler.py")

        fixture_root = self.repo / "tests" / "fixtures"
        shutil.copytree(FIXTURES / "src", fixture_root / "src")
        shutil.copytree(FIXTURES / "wiki", fixture_root / "wiki")
        self.src = self.repo / "inputs" / "src"
        self.wiki = self.repo / "inputs" / "wiki"
        shutil.copytree(FIXTURES / "src", self.src)
        shutil.copytree(FIXTURES / "wiki", self.wiki)

        self.artifact_root = self.repo / "artifacts" / "bg3-label"
        self.generated_root = self.artifact_root / "generated"
        self.evidence_path = (
            self.repo
            / "artifacts"
            / "tooling"
            / "bg3-label-core"
            / "operator-result.json"
        )
        self.latest_evidence_path = (
            self.repo / "artifacts" / "tooling" / "latest" / "bg3-label-core.json"
        )

        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        for name, value in (
            ("REPO_ROOT", self.repo),
            ("ARTIFACT_ROOT", self.artifact_root),
            ("GENERATED_ROOT", self.generated_root),
            ("EVIDENCE_PATH", self.evidence_path),
            ("LATEST_EVIDENCE_PATH", self.latest_evidence_path),
        ):
            self.patches.enter_context(mock.patch.object(operator, name, value))
        self.patches.enter_context(
            mock.patch.object(operator, "source_sha", return_value=TEST_SHA)
        )
        self.patches.enter_context(
            mock.patch.object(operator, "worktree_dirty", return_value=False)
        )

    def apply(self, run_name: str = "test-run") -> dict[str, object]:
        return operator.apply_operation(
            src_raw=self.src,
            wiki_raw=self.wiki,
            run_name=run_name,
            approved=True,
        )

    def test_plan_is_read_only_and_reports_every_task(self) -> None:
        source_before = _snapshot(self.src)
        wiki_before = _snapshot(self.wiki)

        result = operator.plan_operation(
            src_raw=self.src,
            wiki_raw=self.wiki,
            run_name="read-only",
        )

        self.assertTrue(result["read_only"])
        self.assertTrue(all(result["mutation_check"].values()))
        self.assertEqual(len(result["operations"]), result["report"]["total_tasks"])
        statuses = [item["status"] for item in result["operations"]]
        self.assertEqual(statuses.count("planned"), 6)
        self.assertEqual(statuses.count("missing_source"), 1)
        self.assertFalse(self.artifact_root.exists())
        self.assertEqual(_snapshot(self.src), source_before)
        self.assertEqual(_snapshot(self.wiki), wiki_before)

    def test_apply_requires_approval_and_repeat_is_idempotent(self) -> None:
        source_before = _snapshot(self.src)
        wiki_before = _snapshot(self.wiki)
        with self.assertRaisesRegex(operator.LabelOperatorError, "APPROVE=1"):
            operator.apply_operation(
                src_raw=self.src,
                wiki_raw=self.wiki,
                run_name="approved-only",
                approved=False,
            )
        self.assertFalse(self.artifact_root.exists())

        first = self.apply("approved-only")
        second = self.apply("approved-only")

        run_root, labels_root, _, marker_path, report_path = operator.run_paths(
            "approved-only"
        )
        self.assertTrue(run_root.is_dir())
        self.assertTrue(marker_path.is_file())
        self.assertTrue(report_path.is_file())
        self.assertEqual(first["report"]["copied"], 6)
        self.assertEqual(second["report"]["copied"], 0)
        self.assertEqual(second["report"]["skipped_existing"], 6)
        self.assertTrue(second["idempotent_repeat"])
        self.assertEqual(first["output_hashes"], second["output_hashes"])
        self.assertEqual(set(operator.tree_hashes(labels_root)), set(first["output_hashes"]))
        self.assertEqual(_snapshot(self.src), source_before)
        self.assertEqual(_snapshot(self.wiki), wiki_before)

    def test_apply_refuses_unowned_targets_and_unsafe_names(self) -> None:
        with self.assertRaises(operator.LabelOperatorError):
            operator.plan_operation(
                src_raw=self.src,
                wiki_raw=self.wiki,
                run_name="../escape",
            )

        unowned = self.generated_root / "unowned"
        unowned.mkdir(parents=True)
        (unowned / "keep.txt").write_text("operator must not replace me\n")
        with self.assertRaisesRegex(operator.LabelOperatorError, "not owned"):
            self.apply("unowned")
        self.assertTrue((unowned / "keep.txt").is_file())

    def test_failed_new_apply_removes_only_its_incomplete_run(self) -> None:
        source_before = _snapshot(self.src)
        sibling = self.generated_root / "existing-run"
        sibling.mkdir(parents=True)
        (sibling / "keep.txt").write_text("keep\n", encoding="utf-8")

        with (
            mock.patch.object(
                operator,
                "_run_labeler",
                side_effect=OSError("simulated copy failure"),
            ),
            self.assertRaisesRegex(OSError, "simulated copy failure"),
        ):
            self.apply("failed-run")

        self.assertFalse((self.generated_root / "failed-run").exists())
        self.assertTrue((sibling / "keep.txt").is_file())
        self.assertEqual(_snapshot(self.src), source_before)

    def test_rollback_requires_confirmation_and_refuses_modified_output(self) -> None:
        source_before = _snapshot(self.src)
        wiki_before = _snapshot(self.wiki)
        result = self.apply("rollback-test")
        run_root, labels_root, _, _, report_path = operator.run_paths("rollback-test")
        sibling = self.generated_root / "unrelated-run"
        sibling.mkdir()
        (sibling / "keep.txt").write_text("keep\n", encoding="utf-8")

        with self.assertRaisesRegex(operator.LabelOperatorError, "CONFIRM=1"):
            operator.rollback_operation(run_name="rollback-test", confirmed=False)

        relative_output = next(iter(result["output_hashes"]))
        output = labels_root / relative_output
        original = output.read_bytes()
        output.write_bytes(original + b"tampered")
        with self.assertRaisesRegex(operator.LabelOperatorError, "modified"):
            operator.rollback_operation(run_name="rollback-test", confirmed=True)
        self.assertTrue(run_root.exists())

        output.write_bytes(original)
        original_report = report_path.read_bytes()
        report_path.write_bytes(original_report + b"tampered")
        with self.assertRaisesRegex(operator.LabelOperatorError, "report was modified"):
            operator.rollback_operation(run_name="rollback-test", confirmed=True)
        self.assertTrue(run_root.exists())

        report_path.write_bytes(original_report)
        rollback = operator.rollback_operation(
            run_name="rollback-test",
            confirmed=True,
        )
        self.assertEqual(rollback["status"], "pass")
        self.assertFalse(run_root.exists())
        self.assertTrue((sibling / "keep.txt").is_file())
        self.assertEqual(_snapshot(self.src), source_before)
        self.assertEqual(_snapshot(self.wiki), wiki_before)

    def test_doctor_is_stage_aware_and_read_only(self) -> None:
        arguments = {
            "src": str(self.src),
            "wiki": str(self.wiki),
            "run_name": "doctor-run",
            "src_suffix": ".wem.wav",
            "dst_suffix": ".wav",
        }
        with (
            mock.patch.object(operator, "worktree_dirty", return_value=True),
            mock.patch.dict(os.environ, {}, clear=True),
        ):
            plan = operator.doctor_payload(Namespace(stage="plan", **arguments))
            apply = operator.doctor_payload(Namespace(stage="apply", **arguments))

        plan_checks = {item["name"]: item for item in plan["checks"]}
        apply_checks = {item["name"]: item for item in apply["checks"]}
        self.assertEqual(plan["status"], "pass")
        self.assertEqual(plan_checks["clean_worktree"]["status"], "pass")
        self.assertEqual(apply["status"], "fail")
        self.assertEqual(apply_checks["clean_worktree"]["status"], "fail")
        self.assertEqual(apply_checks["approval"]["status"], "fail")
        self.assertFalse(self.artifact_root.exists())

    def test_smoke_writes_clean_current_sha_evidence_and_cleans_up(self) -> None:
        result = operator.smoke_operation()

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["source_sha"], TEST_SHA)
        self.assertTrue(result["worktree_clean"])
        self.assertEqual(result["golden_path_result"], "pass")
        self.assertTrue(self.evidence_path.is_file())
        self.assertTrue(self.latest_evidence_path.is_file())
        self.assertFalse(self.generated_root.exists())
        self.assertEqual(result["cleanup"]["status"], "pass")
        self.assertEqual(result["rollback"]["status"], "pass")


if __name__ == "__main__":
    unittest.main()
