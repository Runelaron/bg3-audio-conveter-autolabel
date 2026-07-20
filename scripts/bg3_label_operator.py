#!/usr/bin/env python3
"""Operate the bounded, source-preserving BG3 label pipeline."""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from datetime import UTC, datetime
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Callable


sys.dont_write_bytecode = True


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from auto_labeler import categorise_wems  # noqa: E402


SCHEMA_VERSION = 1
REPOSITORY = "bg3-audio-converter-autolabel-fix"
PROFILE = "label-fixture-core"
PROOF_CLASS = "core-real"
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "bg3-label"
GENERATED_ROOT = ARTIFACT_ROOT / "generated"
EVIDENCE_PATH = (
    REPO_ROOT
    / "artifacts"
    / "tooling"
    / "bg3-label-core"
    / "operator-result.json"
)
LATEST_EVIDENCE_PATH = (
    REPO_ROOT / "artifacts" / "tooling" / "latest" / "bg3-label-core.json"
)
RUN_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
METADATA_DIR_NAME = ".bg3-label"
OWNERSHIP_FILE_NAME = "ownership.json"
REPORT_FILE_NAME = "report.json"


class LabelOperatorError(RuntimeError):
    """A safe label-operator contract failure."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def git_output(*args: str) -> str:
    process = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode:
        detail = process.stderr.strip() or process.stdout.strip()
        raise LabelOperatorError(f"git {' '.join(args)} failed: {detail}")
    return process.stdout.strip()


def source_sha() -> str:
    return git_output("rev-parse", "HEAD")


def worktree_dirty() -> bool:
    return bool(git_output("status", "--porcelain"))


def atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_hashes(
    root: Path,
    *,
    include: Callable[[Path], bool] | None = None,
) -> dict[str, str]:
    """Hash regular files below a root while refusing symlink traversal."""

    if not root.exists():
        return {}
    if root.is_symlink() or not root.is_dir():
        raise LabelOperatorError(f"Expected a real directory, not a symlink: {root}")
    hashes: dict[str, str] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise LabelOperatorError(f"Symlinks are not allowed in operator trees: {path}")
        if not path.is_file() or (include is not None and not include(path)):
            continue
        hashes[path.relative_to(root).as_posix()] = file_sha256(path)
    return hashes


def manifest_digest(payload: dict[str, str]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def input_identity(src: Path, wiki: Path, src_suffix: str) -> dict[str, object]:
    source_hashes = tree_hashes(
        src,
        include=lambda path: path.name.endswith(src_suffix),
    )
    wiki_hashes = tree_hashes(wiki, include=lambda path: path.suffix == ".md")
    return {
        "source_file_count": len(source_hashes),
        "source_digest": manifest_digest(source_hashes),
        "wiki_file_count": len(wiki_hashes),
        "wiki_digest": manifest_digest(wiki_hashes),
    }


def resolve_input_dir(raw: str | Path, label: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise LabelOperatorError(f"{label} directory does not exist: {path}") from exc
    if not resolved.is_dir():
        raise LabelOperatorError(f"{label} path is not a directory: {resolved}")
    artifact_root = ARTIFACT_ROOT.resolve(strict=False)
    if resolved == artifact_root or artifact_root in resolved.parents:
        raise LabelOperatorError(
            f"{label} must stay outside the owned generated artifact root."
        )
    return resolved


def validate_run_name(run_name: str) -> str:
    if not RUN_NAME_PATTERN.fullmatch(run_name) or run_name in {".", ".."}:
        raise LabelOperatorError(
            "run name must be 1-80 letters, digits, dots, underscores, or dashes"
        )
    return run_name


def _reject_symlinked_operator_roots() -> None:
    repo_root = REPO_ROOT.resolve()
    for path in (REPO_ROOT / "artifacts", ARTIFACT_ROOT, GENERATED_ROOT):
        if path.exists() and path.is_symlink():
            raise LabelOperatorError(f"Owned operator root may not be a symlink: {path}")
        resolved = path.resolve(strict=False)
        if resolved != repo_root and repo_root not in resolved.parents:
            raise LabelOperatorError(f"Owned operator root escaped the repository: {path}")


def run_paths(run_name: str) -> tuple[Path, Path, Path, Path, Path]:
    validate_run_name(run_name)
    _reject_symlinked_operator_roots()
    generated_root = GENERATED_ROOT.resolve(strict=False)
    run_root = (GENERATED_ROOT / run_name).resolve(strict=False)
    if run_root.parent != generated_root:
        raise LabelOperatorError("Generated run path escaped the owned output root.")
    if run_root.exists() and run_root.is_symlink():
        raise LabelOperatorError(f"Generated run may not be a symlink: {run_root}")
    labels_root = run_root / "labels"
    metadata_root = run_root / METADATA_DIR_NAME
    marker_path = metadata_root / OWNERSHIP_FILE_NAME
    report_path = metadata_root / REPORT_FILE_NAME
    return run_root, labels_root, metadata_root, marker_path, report_path


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LabelOperatorError(f"Invalid operator JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise LabelOperatorError(f"Operator JSON must be an object: {path}")
    return payload


def load_marker(run_name: str) -> dict[str, Any] | None:
    run_root, labels_root, metadata_root, marker_path, _ = run_paths(run_name)
    del labels_root
    if not run_root.exists():
        return None
    if (
        not run_root.is_dir()
        or metadata_root.is_symlink()
        or not metadata_root.is_dir()
        or not marker_path.is_file()
        or marker_path.is_symlink()
    ):
        raise LabelOperatorError(
            f"Existing run is not owned by this operator; refusing: {run_root}"
        )
    marker = _read_json(marker_path)
    if (
        marker.get("schema_version") != SCHEMA_VERSION
        or marker.get("repository") != REPOSITORY
        or marker.get("run_name") != run_name
        or marker.get("generated_root") != str(run_root)
    ):
        raise LabelOperatorError(f"Ownership marker does not match run: {run_root}")
    return marker


def _validate_ready_run(run_name: str, marker: dict[str, Any]) -> dict[str, str]:
    run_root, labels_root, metadata_root, marker_path, report_path = run_paths(run_name)
    if (
        marker.get("state") != "ready"
        or labels_root.is_symlink()
        or not labels_root.is_dir()
        or metadata_root.is_symlink()
        or not metadata_root.is_dir()
        or report_path.is_symlink()
        or not report_path.is_file()
    ):
        raise LabelOperatorError(
            f"Generated run is incomplete; inspect it before rollback or reuse: {run_root}"
        )
    expected_report_sha = marker.get("report_sha256")
    if (
        not isinstance(expected_report_sha, str)
        or file_sha256(report_path) != expected_report_sha
    ):
        raise LabelOperatorError(
            "Generated report was modified after apply; refusing to overwrite or remove it."
        )
    current_hashes = tree_hashes(labels_root)
    expected_hashes = marker.get("output_hashes")
    if (
        not isinstance(expected_hashes, dict)
        or not all(
            isinstance(path, str) and isinstance(digest, str)
            for path, digest in expected_hashes.items()
        )
        or current_hashes != expected_hashes
    ):
        raise LabelOperatorError(
            "Generated labels were modified after apply; refusing to overwrite or remove them."
        )
    allowed_metadata = {marker_path.resolve(), report_path.resolve()}
    for path in sorted(run_root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise LabelOperatorError(f"Generated run contains a symlink: {path}")
        if path == labels_root or labels_root in path.parents:
            continue
        if path == metadata_root:
            continue
        if not path.is_file() or path.resolve() not in allowed_metadata:
            raise LabelOperatorError(
                f"Generated run contains untracked content; refusing mutation: {path}"
            )
    return current_hashes


def _normalise_operations(
    operations: list[dict[str, object]],
    src: Path,
    labels_root: Path,
) -> list[dict[str, object]]:
    normalised: list[dict[str, object]] = []
    for operation in operations:
        item = dict(operation)
        raw_source = item.get("source")
        if raw_source:
            source = Path(str(raw_source)).resolve()
            try:
                item["source"] = source.relative_to(src).as_posix()
            except ValueError:
                raise LabelOperatorError(
                    f"Planned source escaped the declared source root: {source}"
                ) from None
        destination = Path(str(item["destination"])).resolve(strict=False)
        try:
            item["destination"] = destination.relative_to(labels_root).as_posix()
        except ValueError:
            raise LabelOperatorError(
                f"Planned destination escaped the owned labels root: {destination}"
            ) from None
        normalised.append(item)
    return normalised


def _run_labeler(
    *,
    src: Path,
    wiki: Path,
    labels_root: Path,
    src_suffix: str,
    dst_suffix: str,
    dry_run: bool,
) -> tuple[dict[str, object], list[dict[str, object]], list[str]]:
    operations: list[dict[str, object]] = []
    captured = io.StringIO()
    with redirect_stdout(captured):
        report = categorise_wems(
            wiki,
            src,
            labels_root,
            src_suffix=src_suffix,
            dst_suffix=dst_suffix,
            duplicate_mode="copy",
            conflict_mode="suffix",
            dry_run=dry_run,
            on_operation=operations.append,
        )
    diagnostics = [line for line in captured.getvalue().splitlines() if line]
    return report, _normalise_operations(operations, src, labels_root), diagnostics


def _validate_suffix(value: str, label: str) -> str:
    if not value.startswith(".") or any(char in value for char in ("/", "\\", "\0")):
        raise LabelOperatorError(f"{label} must be a simple suffix beginning with '.'.")
    return value


def plan_operation(
    *,
    src_raw: str | Path,
    wiki_raw: str | Path,
    run_name: str,
    src_suffix: str = ".wem.wav",
    dst_suffix: str = ".wav",
) -> dict[str, object]:
    """Build and return a fully read-only labeling plan."""

    src_suffix = _validate_suffix(src_suffix, "source suffix")
    dst_suffix = _validate_suffix(dst_suffix, "destination suffix")
    src = resolve_input_dir(src_raw, "source")
    wiki = resolve_input_dir(wiki_raw, "wiki")
    run_root, labels_root, _, _, _ = run_paths(run_name)
    marker = load_marker(run_name)
    if marker is not None:
        _validate_ready_run(run_name, marker)

    artifact_root_existed = ARTIFACT_ROOT.exists()
    generated_root_existed = GENERATED_ROOT.exists()
    run_root_existed = run_root.exists()
    inputs_before = input_identity(src, wiki, src_suffix)
    generated_before = tree_hashes(run_root) if run_root.exists() else {}
    report, operations, diagnostics = _run_labeler(
        src=src,
        wiki=wiki,
        labels_root=labels_root,
        src_suffix=src_suffix,
        dst_suffix=dst_suffix,
        dry_run=True,
    )
    inputs_after = input_identity(src, wiki, src_suffix)
    generated_after = tree_hashes(run_root) if run_root.exists() else {}
    mutation_check = {
        "inputs_unchanged": inputs_before == inputs_after,
        "generated_output_unchanged": generated_before == generated_after,
        "artifact_root_unchanged": ARTIFACT_ROOT.exists() == artifact_root_existed,
        "generated_root_unchanged": GENERATED_ROOT.exists() == generated_root_existed,
        "run_root_unchanged": run_root.exists() == run_root_existed,
    }
    if not all(mutation_check.values()):
        raise LabelOperatorError("Read-only plan mutation check failed.")

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "pass",
        "command": "label-plan",
        "read_only": True,
        "repository": REPOSITORY,
        "source_sha": source_sha(),
        "worktree_clean": not worktree_dirty(),
        "profile": PROFILE,
        "proof_class": PROOF_CLASS,
        "run_name": run_name,
        "source_root": str(src),
        "wiki_root": str(wiki),
        "generated_root": str(run_root),
        "labels_root": str(labels_root),
        "input_identity": inputs_before,
        "report": report,
        "operations": operations,
        "diagnostics": diagnostics,
        "mutation_check": mutation_check,
        "approval_required": "APPROVE=1",
    }


def _create_owned_run(
    *,
    run_name: str,
    src: Path,
    wiki: Path,
    inputs: dict[str, object],
    current_sha: str,
) -> dict[str, Any]:
    run_root, labels_root, metadata_root, marker_path, _ = run_paths(run_name)
    GENERATED_ROOT.mkdir(parents=True, exist_ok=True)
    run_root.mkdir(exist_ok=False)
    labels_root.mkdir()
    metadata_root.mkdir()
    marker: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "repository": REPOSITORY,
        "run_name": run_name,
        "generated_root": str(run_root),
        "labels_root": str(labels_root),
        "source_root": str(src),
        "wiki_root": str(wiki),
        "source_sha": current_sha,
        "input_identity": inputs,
        "state": "applying",
        "created_at": utc_now(),
    }
    atomic_json(marker_path, marker)
    return marker


def _discard_incomplete_new_run(run_name: str) -> None:
    """Best-effort cleanup for a run created by a failed apply transaction."""

    run_root, _, _, _, _ = run_paths(run_name)
    if not run_root.exists():
        return
    try:
        marker = load_marker(run_name)
    except LabelOperatorError:
        return
    if marker is None or marker.get("state") != "applying":
        return
    shutil.rmtree(run_root)
    if GENERATED_ROOT.exists() and not any(GENERATED_ROOT.iterdir()):
        GENERATED_ROOT.rmdir()


def apply_operation(
    *,
    src_raw: str | Path,
    wiki_raw: str | Path,
    run_name: str,
    approved: bool,
    src_suffix: str = ".wem.wav",
    dst_suffix: str = ".wav",
) -> dict[str, object]:
    """Apply a copy-only plan inside one owned generated run."""

    if not approved:
        raise LabelOperatorError("label-apply requires APPROVE=1.")
    if worktree_dirty():
        raise LabelOperatorError("label-apply requires a clean worktree.")
    current_sha = source_sha()
    src_suffix = _validate_suffix(src_suffix, "source suffix")
    dst_suffix = _validate_suffix(dst_suffix, "destination suffix")
    src = resolve_input_dir(src_raw, "source")
    wiki = resolve_input_dir(wiki_raw, "wiki")
    run_root, labels_root, _, marker_path, report_path = run_paths(run_name)
    inputs_before = input_identity(src, wiki, src_suffix)
    marker = load_marker(run_name)
    repeat_apply = marker is not None
    if marker is None:
        marker = _create_owned_run(
            run_name=run_name,
            src=src,
            wiki=wiki,
            inputs=inputs_before,
            current_sha=current_sha,
        )
        output_before: dict[str, str] = {}
    else:
        output_before = _validate_ready_run(run_name, marker)
        if (
            marker.get("source_sha") != current_sha
            or marker.get("source_root") != str(src)
            or marker.get("wiki_root") != str(wiki)
            or marker.get("input_identity") != inputs_before
        ):
            raise LabelOperatorError(
                "Run SHA or inputs changed after the first apply; choose a new run name."
            )

    try:
        report, operations, diagnostics = _run_labeler(
            src=src,
            wiki=wiki,
            labels_root=labels_root,
            src_suffix=src_suffix,
            dst_suffix=dst_suffix,
            dry_run=False,
        )
        inputs_after = input_identity(src, wiki, src_suffix)
        if inputs_after != inputs_before:
            raise LabelOperatorError(
                "Source or wiki content changed during copy-only apply."
            )
        if source_sha() != current_sha or worktree_dirty():
            raise LabelOperatorError(
                "Repository SHA or clean-worktree state changed during apply."
            )
        output_after = tree_hashes(labels_root)
        idempotent_repeat = output_before == output_after if repeat_apply else None
        if repeat_apply and not idempotent_repeat:
            raise LabelOperatorError("Repeated apply changed generated output.")

        payload: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "status": "pass",
            "command": "label-apply",
            "approved": True,
            "repository": REPOSITORY,
            "source_sha": current_sha,
            "worktree_clean": True,
            "profile": PROFILE,
            "proof_class": PROOF_CLASS,
            "run_name": run_name,
            "source_root": str(src),
            "wiki_root": str(wiki),
            "generated_root": str(run_root),
            "labels_root": str(labels_root),
            "report_path": str(report_path),
            "input_identity": inputs_before,
            "input_preservation": {"status": "pass", "unchanged": True},
            "report": report,
            "operations": operations,
            "diagnostics": diagnostics,
            "output_hashes": output_after,
            "output_digest": manifest_digest(output_after),
            "repeat_apply": repeat_apply,
            "idempotent_repeat": idempotent_repeat,
            "rollback_command": (
                f"CONFIRM=1 ./scripts/label-rollback --run-name {run_name}"
            ),
        }
        atomic_json(report_path, payload)
        marker.update(
            {
                "state": "ready",
                "last_apply_at": utc_now(),
                "source_sha": current_sha,
                "input_identity": inputs_before,
                "output_hashes": output_after,
                "output_digest": manifest_digest(output_after),
                "report_path": str(report_path),
                "report_sha256": file_sha256(report_path),
            }
        )
        atomic_json(marker_path, marker)
        return payload
    except Exception:
        if not repeat_apply:
            _discard_incomplete_new_run(run_name)
        raise


def rollback_operation(*, run_name: str, confirmed: bool) -> dict[str, object]:
    """Remove exactly one confirmed, unmodified, operator-owned generated run."""

    if not confirmed:
        raise LabelOperatorError("label-rollback requires CONFIRM=1.")
    run_root, _, _, _, _ = run_paths(run_name)
    marker = load_marker(run_name)
    if marker is None:
        raise LabelOperatorError(f"Owned generated run does not exist: {run_root}")
    output_hashes = _validate_ready_run(run_name, marker)
    source_root = Path(str(marker["source_root"])).resolve(strict=False)
    wiki_root = Path(str(marker["wiki_root"])).resolve(strict=False)
    if (
        run_root == source_root
        or run_root in source_root.parents
        or source_root in run_root.parents
    ):
        raise LabelOperatorError("Refusing rollback because source overlaps output.")
    if (
        run_root == wiki_root
        or run_root in wiki_root.parents
        or wiki_root in run_root.parents
    ):
        raise LabelOperatorError("Refusing rollback because wiki overlaps output.")

    shutil.rmtree(run_root)
    if GENERATED_ROOT.exists() and not any(GENERATED_ROOT.iterdir()):
        GENERATED_ROOT.rmdir()
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "pass",
        "command": "label-rollback",
        "repository": REPOSITORY,
        "source_sha": source_sha(),
        "run_name": run_name,
        "removed_root": str(run_root),
        "removed_file_count": len(output_hashes),
        "source_root": str(source_root),
        "wiki_root": str(wiki_root),
        "source_assets_removed": False,
        "confirmed": True,
    }


def _resolve_optional_inputs(args: argparse.Namespace) -> tuple[str, str]:
    src = args.src or os.getenv("BG3_LABEL_SOURCE", "")
    wiki = args.wiki or os.getenv("SIDS_WIKI", "")
    if not src:
        raise LabelOperatorError("Define --src or BG3_LABEL_SOURCE.")
    if not wiki:
        raise LabelOperatorError("Define --wiki or SIDS_WIKI.")
    return src, wiki


def doctor_payload(args: argparse.Namespace) -> dict[str, object]:
    """Return a stage-aware, read-only readiness report."""

    checks: list[dict[str, object]] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append(
            {"name": name, "status": "pass" if passed else "fail", "detail": detail}
        )

    add(
        "python",
        sys.version_info >= (3, 12),
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    )
    try:
        sha = source_sha()
        add("git_repository", True, str(REPO_ROOT))
    except LabelOperatorError as exc:
        sha = "unknown"
        add("git_repository", False, str(exc))
    dirty = worktree_dirty() if sha != "unknown" else True
    clean_required = args.stage in {"apply", "smoke"}
    add(
        "clean_worktree",
        not dirty or not clean_required,
        "clean"
        if not dirty
        else f"dirty; {'required' if clean_required else 'allowed for read-only planning'}",
    )
    add(
        "conversion_tools",
        True,
        "not required for label-only plan/apply/rollback/smoke stages",
    )

    if args.stage in {"plan", "apply"}:
        resolved_src: Path | None = None
        resolved_wiki: Path | None = None
        resolved_identity: dict[str, object] | None = None
        try:
            src_suffix = _validate_suffix(args.src_suffix, "source suffix")
            _validate_suffix(args.dst_suffix, "destination suffix")
            src_raw, wiki_raw = _resolve_optional_inputs(args)
            resolved_src = resolve_input_dir(src_raw, "source")
            resolved_wiki = resolve_input_dir(wiki_raw, "wiki")
            resolved_identity = input_identity(
                resolved_src,
                resolved_wiki,
                src_suffix,
            )
            source_count = int(resolved_identity["source_file_count"])
            wiki_count = int(resolved_identity["wiki_file_count"])
            add(
                "source_root",
                source_count > 0,
                f"{resolved_src} ({source_count} candidates)",
            )
            add(
                "wiki_root",
                wiki_count > 0,
                f"{resolved_wiki} ({wiki_count} markdown files)",
            )
        except LabelOperatorError as exc:
            add("label_inputs", False, str(exc))
        try:
            run_root, _, _, _, _ = run_paths(args.run_name)
            marker = load_marker(args.run_name)
            if marker is not None:
                _validate_ready_run(args.run_name, marker)
                if args.stage == "apply" and (
                    marker.get("source_sha") != sha
                    or marker.get("source_root") != str(resolved_src)
                    or marker.get("wiki_root") != str(resolved_wiki)
                    or marker.get("input_identity") != resolved_identity
                ):
                    raise LabelOperatorError(
                        "Existing run SHA or inputs do not match this apply."
                    )
            add(
                "generated_output",
                True,
                f"owned target {'ready' if marker else 'available'}: {run_root}",
            )
        except LabelOperatorError as exc:
            add("generated_output", False, str(exc))
        if args.stage == "apply":
            add(
                "approval",
                os.getenv("APPROVE") == "1",
                "APPROVE=1 present"
                if os.getenv("APPROVE") == "1"
                else "APPROVE=1 required",
            )
    elif args.stage == "rollback":
        try:
            run_root, _, _, _, _ = run_paths(args.run_name)
            marker = load_marker(args.run_name)
            if marker is None:
                raise LabelOperatorError(f"Owned generated run does not exist: {run_root}")
            _validate_ready_run(args.run_name, marker)
            add("owned_run", True, str(run_root))
        except LabelOperatorError as exc:
            add("owned_run", False, str(exc))
        add(
            "confirmation",
            os.getenv("CONFIRM") == "1",
            "CONFIRM=1 present"
            if os.getenv("CONFIRM") == "1"
            else "CONFIRM=1 required",
        )
    else:
        fixture_src = REPO_ROOT / "tests" / "fixtures" / "src"
        fixture_wiki = REPO_ROOT / "tests" / "fixtures" / "wiki"
        add("fixture_source", fixture_src.is_dir(), str(fixture_src))
        add("fixture_wiki", fixture_wiki.is_dir(), str(fixture_wiki))
        try:
            _reject_symlinked_operator_roots()
            add("evidence_root", True, str(EVIDENCE_PATH.parent))
        except LabelOperatorError as exc:
            add("evidence_root", False, str(exc))

    status = "pass" if all(item["status"] == "pass" for item in checks) else "fail"
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "command": "label-doctor",
        "stage": args.stage,
        "read_only": True,
        "repository": REPOSITORY,
        "source_sha": sha,
        "profile": PROFILE,
        "proof_class": PROOF_CLASS,
        "checks": checks,
    }


def smoke_operation() -> dict[str, object]:
    """Run plan/apply/repeat/rollback against tracked deterministic fixtures."""

    sha = source_sha()
    if worktree_dirty():
        raise LabelOperatorError("label-smoke evidence requires a clean worktree.")
    src = REPO_ROOT / "tests" / "fixtures" / "src"
    wiki = REPO_ROOT / "tests" / "fixtures" / "wiki"
    run_name = (
        f"smoke-{sha[:12]}-"
        f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}"
    )
    doctor = doctor_payload(
        argparse.Namespace(
            stage="smoke",
            src="",
            wiki="",
            run_name=run_name,
            src_suffix=".wem.wav",
            dst_suffix=".wav",
        )
    )
    if doctor["status"] != "pass":
        raise LabelOperatorError("Stage-aware smoke doctor did not pass.")
    source_before = tree_hashes(src)
    wiki_before = tree_hashes(wiki)
    plan = plan_operation(src_raw=src, wiki_raw=wiki, run_name=run_name)
    if not plan["read_only"] or not plan["mutation_check"]["inputs_unchanged"]:
        raise LabelOperatorError("Smoke plan did not prove read-only behavior.")
    first = apply_operation(
        src_raw=src,
        wiki_raw=wiki,
        run_name=run_name,
        approved=True,
    )
    second = apply_operation(
        src_raw=src,
        wiki_raw=wiki,
        run_name=run_name,
        approved=True,
    )
    idempotent = (
        first["output_hashes"] == second["output_hashes"]
        and second["idempotent_repeat"] is True
        and int(second["report"]["copied"]) == 0
        and int(second["report"]["skipped_existing"])
        == int(second["report"]["labeled"])
    )
    if not idempotent:
        raise LabelOperatorError("Repeated approved apply was not idempotent.")

    refusal = ""
    try:
        rollback_operation(run_name=run_name, confirmed=False)
    except LabelOperatorError as exc:
        refusal = str(exc)
    if "CONFIRM=1" not in refusal:
        raise LabelOperatorError("Rollback confirmation refusal was not enforced.")
    rollback = rollback_operation(run_name=run_name, confirmed=True)
    run_root, _, _, _, _ = run_paths(run_name)
    source_after = tree_hashes(src)
    wiki_after = tree_hashes(wiki)
    source_preserved = source_before == source_after and wiki_before == wiki_after
    cleanup_passed = not run_root.exists() and source_preserved
    if not cleanup_passed:
        raise LabelOperatorError("Smoke rollback or source-preservation check failed.")

    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "pass",
        "generated_at": utc_now(),
        "repository": REPOSITORY,
        "source_sha": sha,
        "worktree_clean": not worktree_dirty(),
        "profile": PROFILE,
        "proof_class": PROOF_CLASS,
        "golden_path_result": "pass",
        "golden_path": [
            "run stage-aware label doctor against tracked inputs",
            "plan exact copy-only label operations without filesystem mutation",
            "apply only after APPROVE=1 semantics into an owned generated run",
            "inspect the generated report and labeled files",
            "repeat the same apply and confirm byte-identical output with no copies",
            "refuse unconfirmed rollback, then remove only the confirmed owned run",
            "confirm source audio and wiki fixtures retain their original hashes",
        ],
        "plan": {
            "status": plan["status"],
            "read_only": plan["read_only"],
            "total_tasks": plan["report"]["total_tasks"],
            "operation_count": len(plan["operations"]),
            "mutation_check": plan["mutation_check"],
        },
        "doctor": doctor,
        "first_apply": {
            "status": first["status"],
            "approved": first["approved"],
            "labeled": first["report"]["labeled"],
            "missing_sources": first["report"]["missing_sources"],
            "output_hashes": first["output_hashes"],
            "report": first["report"],
        },
        "repeat_apply": {
            "status": second["status"],
            "idempotent": idempotent,
            "copied": second["report"]["copied"],
            "skipped_existing": second["report"]["skipped_existing"],
            "output_digest": second["output_digest"],
        },
        "user_visible_outcome": {
            "labeled_files": sorted(first["output_hashes"]),
            "labeled_count": first["report"]["labeled"],
            "known_missing_count": first["report"]["missing_sources"],
            "report_generated": True,
        },
        "input_preservation": {
            "status": "pass" if source_preserved else "fail",
            "source_assets_unchanged": source_before == source_after,
            "wiki_unchanged": wiki_before == wiki_after,
        },
        "rollback": {
            "status": rollback["status"],
            "confirmation_refusal": refusal,
            "owned_run_removed": not run_root.exists(),
            "source_assets_removed": rollback["source_assets_removed"],
        },
        "cleanup": {
            "status": "pass" if cleanup_passed else "fail",
            "owned_run_removed": not run_root.exists(),
            "source_assets_preserved": source_preserved,
        },
        "restart_persistence": {
            "status": "not-applicable",
            "reason": "The label slice is a one-shot filesystem transformation.",
        },
        "dependency_identities": {
            "python": (
                f"{sys.version_info.major}.{sys.version_info.minor}."
                f"{sys.version_info.micro}"
            ),
            "auto_labeler_sha256": file_sha256(REPO_ROOT / "auto_labeler.py"),
            "third_party_runtime_packages": [],
        },
        "internal_boundaries": {
            "planner": "real auto_labeler task/source resolution and conflict logic",
            "apply": "real copy-only materialisation and JSON reporting",
            "rollback": "owned-marker and hash-verified generated-run cleanup",
        },
        "external_boundaries": {
            "game_assets": "tracked deterministic source fixtures",
            "sid_wiki": "tracked deterministic markdown fixture",
            "vgmstream_wwiser": "not required for the label-only stable slice",
            "network_paid_calls": "none",
        },
        "claim_boundary": (
            "Core-real label planning, copying, reporting, idempotence, and rollback "
            "against tracked fixtures; no claim about full BG3 corpus coverage, audio "
            "conversion, bank decoding, or wiki completeness."
        ),
        "rollback_reference": (
            f"CONFIRM=1 ./scripts/label-rollback --run-name {run_name}"
        ),
    }
    if not payload["worktree_clean"]:
        raise LabelOperatorError("Worktree became dirty during smoke.")
    atomic_json(EVIDENCE_PATH, payload)
    atomic_json(LATEST_EVIDENCE_PATH, payload)
    return payload


def add_input_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--src", default="")
    parser.add_argument("--wiki", default="")
    parser.add_argument("--run-name", default=os.getenv("BG3_LABEL_RUN", "default"))
    parser.add_argument("--src-suffix", default=".wem.wav")
    parser.add_argument("--dst-suffix", default=".wav")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    doctor = subparsers.add_parser("doctor")
    doctor.add_argument(
        "--stage",
        choices=("plan", "apply", "rollback", "smoke"),
        default="plan",
    )
    add_input_options(doctor)
    add_input_options(subparsers.add_parser("plan"))
    add_input_options(subparsers.add_parser("apply"))
    rollback = subparsers.add_parser("rollback")
    rollback.add_argument("--run-name", required=True)
    subparsers.add_parser("smoke")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "doctor":
            payload = doctor_payload(args)
        elif args.command == "plan":
            src, wiki = _resolve_optional_inputs(args)
            payload = plan_operation(
                src_raw=src,
                wiki_raw=wiki,
                run_name=args.run_name,
                src_suffix=args.src_suffix,
                dst_suffix=args.dst_suffix,
            )
        elif args.command == "apply":
            src, wiki = _resolve_optional_inputs(args)
            payload = apply_operation(
                src_raw=src,
                wiki_raw=wiki,
                run_name=args.run_name,
                approved=os.getenv("APPROVE") == "1",
                src_suffix=args.src_suffix,
                dst_suffix=args.dst_suffix,
            )
        elif args.command == "rollback":
            payload = rollback_operation(
                run_name=args.run_name,
                confirmed=os.getenv("CONFIRM") == "1",
            )
        else:
            payload = smoke_operation()
    except (LabelOperatorError, OSError, ValueError, KeyError) as exc:
        print(f"[label-error] {exc}", file=sys.stderr)
        return 2
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
