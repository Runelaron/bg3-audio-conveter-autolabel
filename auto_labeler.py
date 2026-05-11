"""Organize BG3 WAV files into SID-wiki-based folder structures.

Can be imported (`categorise_wems`) or run as a script (see --help).
"""

from __future__ import annotations

import argparse
import filecmp
import hashlib
import json
import os
import re
import shutil
import string
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator


SAFE_CHARS = f"-_. {string.ascii_letters}{string.digits}"
WINDOWS_RESERVED_BASENAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
}
ROW_PATTERN = re.compile(r"^\|\s*\d+\s*\|\s*([^|]+?)\s*\|\s*([0-9, ]+)\s*\|")


@dataclass(frozen=True)
class LabelTask:
    """Destination work item for one SID."""

    sid: str
    dst: Path
    bank_hint: str | None


@dataclass(frozen=True)
class SourceCandidate:
    """One candidate source file for a SID."""

    path: Path
    bank: str | None


@dataclass(frozen=True)
class SourceIndex:
    """Indexed view of candidate source files."""

    by_sid: dict[str, tuple[SourceCandidate, ...]]
    by_bank_sid: dict[tuple[str, str], tuple[SourceCandidate, ...]]
    all_files: tuple[Path, ...]


def _safe(text: str) -> str:
    """Replace unsafe filesystem chars in *text* with underscores."""
    cleaned = "".join(ch if ch in SAFE_CHARS else "_" for ch in text)
    cleaned = cleaned.strip(" .")
    if not cleaned:
        cleaned = "_"
    if cleaned.upper() in WINDOWS_RESERVED_BASENAMES:
        cleaned = f"{cleaned}_"
    return cleaned


def parse_markdown(md: Path) -> Iterator[tuple[str, list[str]]]:
    """Yield (row_name, wem_ids) for each row in SID-wiki markdown."""
    with md.open(encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            match = ROW_PATTERN.match(line)
            if not match:
                continue
            name = _safe(match.group(1).strip())
            ids = [sid.strip() for sid in match.group(2).split(",") if sid.strip()]
            if ids:
                yield name, ids


def _bank_hint_for_markdown(md: Path) -> str | None:
    """Extract bank folder hint from a wiki markdown filename."""
    if not md.name.endswith(".md"):
        return None
    stem = md.name[: -len(".md")]
    if "-&-" not in stem:
        return None
    bank_hint = stem.rsplit("-&-", 1)[1].strip()
    return bank_hint or None


def _candidate_bank(src_dir: Path, file_path: Path) -> str | None:
    """Return the top-level bank folder for *file_path* below *src_dir*."""
    rel_path = file_path.relative_to(src_dir)
    if len(rel_path.parts) <= 1:
        return None
    return rel_path.parts[0]


def build_source_index(src_dir: Path, src_suffix: str) -> SourceIndex:
    """Build immutable mappings of SID candidates globally and by bank."""
    by_sid: dict[str, list[SourceCandidate]] = {}
    by_bank_sid: dict[tuple[str, str], list[SourceCandidate]] = {}
    all_files: list[Path] = []
    pattern = f"*{src_suffix}"
    for file_path in sorted(src_dir.rglob(pattern), key=lambda p: p.as_posix()):
        if not file_path.is_file() or not file_path.name.endswith(src_suffix):
            continue
        sid = file_path.name[: -len(src_suffix)]
        if not sid:
            continue
        bank = _candidate_bank(src_dir, file_path)
        candidate = SourceCandidate(path=file_path, bank=bank)
        all_files.append(file_path)
        by_sid.setdefault(sid, []).append(candidate)
        if bank is not None:
            by_bank_sid.setdefault((bank, sid), []).append(candidate)

    return SourceIndex(
        by_sid={sid: tuple(paths) for sid, paths in by_sid.items()},
        by_bank_sid={key: tuple(paths) for key, paths in by_bank_sid.items()},
        all_files=tuple(all_files),
    )


def build_tasks(
    wiki_root: Path,
    dst_root: Path,
    dst_suffix: str = ".wav",
) -> list[LabelTask]:
    """Generate label tasks in a deterministic wiki traversal order."""
    tasks: list[LabelTask] = []
    for md in sorted(wiki_root.rglob("*.md"), key=lambda p: p.as_posix()):
        bank_hint = _bank_hint_for_markdown(md)
        top = dst_root / _safe(md.stem)
        for row_name, ids in parse_markdown(md):
            if len(ids) == 1:
                tasks.append(
                    LabelTask(
                        sid=ids[0],
                        dst=top / f"{row_name}{dst_suffix}",
                        bank_hint=bank_hint,
                    )
                )
                continue
            leaf = top / row_name
            for index, sid in enumerate(ids, 1):
                tasks.append(
                    LabelTask(
                        sid=sid,
                        dst=leaf / f"{index}{dst_suffix}",
                        bank_hint=bank_hint,
                    )
                )
    return tasks


def _resolve_conflict(
    src: Path,
    dst: Path,
    reserved_paths: set[Path],
    conflict_mode: str,
) -> tuple[Path, bool]:
    """Return conflict-safe destination path."""
    if dst not in reserved_paths and _same_file_content(src, dst):
        return dst, False

    if conflict_mode != "suffix":
        return dst, False

    if dst not in reserved_paths and not dst.exists():
        return dst, False

    suffix = 2
    while True:
        candidate = dst.with_name(f"{dst.stem}_{suffix}{dst.suffix}")
        suffix += 1
        if candidate in reserved_paths:
            continue
        if _same_file_content(src, candidate):
            return candidate, True
        if not candidate.exists():
            return candidate, True


def _same_file_content(src: Path, dst: Path) -> bool:
    """Check whether destination already contains the same bytes as source."""
    if not dst.exists() or not dst.is_file():
        return False
    try:
        return filecmp.cmp(src, dst, shallow=False)
    except OSError:
        return False


def _select_mode(duplicate_mode: str, sid_usage_count: int) -> str:
    """Select effective operation mode for a SID."""
    if duplicate_mode == "move" and sid_usage_count == 1:
        return "move"
    if duplicate_mode == "link":
        return "link"
    return "copy"


def _file_signature(
    path: Path,
    signature_cache: dict[Path, tuple[int, str]],
) -> tuple[int, str]:
    """Return stable content signature for *path*."""
    if path in signature_cache:
        return signature_cache[path]

    hasher = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            hasher.update(chunk)

    signature = (path.stat().st_size, hasher.hexdigest())
    signature_cache[path] = signature
    return signature


def _distinct_candidates(
    candidates: Iterable[SourceCandidate],
    signature_cache: dict[Path, tuple[int, str]],
) -> tuple[SourceCandidate, ...]:
    """Collapse byte-identical candidates to a single representative."""
    distinct: list[SourceCandidate] = []
    seen_signatures: set[tuple[int, str]] = set()
    for candidate in candidates:
        signature = _file_signature(candidate.path, signature_cache)
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        distinct.append(candidate)
    return tuple(distinct)


def _resolve_source(
    task: LabelTask,
    source_index: SourceIndex,
    signature_cache: dict[Path, tuple[int, str]],
) -> tuple[SourceCandidate | None, str]:
    """Resolve the best source candidate for *task*."""
    if task.bank_hint is not None:
        bank_candidates = source_index.by_bank_sid.get((task.bank_hint, task.sid), ())
        distinct_bank_candidates = _distinct_candidates(bank_candidates, signature_cache)
        if distinct_bank_candidates:
            if len(distinct_bank_candidates) == 1:
                return distinct_bank_candidates[0], "bank"
            return None, "ambiguous"

    global_candidates = source_index.by_sid.get(task.sid, ())
    distinct_global_candidates = _distinct_candidates(global_candidates, signature_cache)
    if not distinct_global_candidates:
        return None, "missing"
    if len(distinct_global_candidates) == 1:
        return distinct_global_candidates[0], "global_unique"
    return None, "ambiguous"


def materialise(
    tasks: Iterable[LabelTask],
    source_index: SourceIndex,
    duplicate_mode: str,
    conflict_mode: str,
    dry_run: bool,
) -> dict[str, object]:
    """Create needed folders and copy/move/link files as specified."""
    task_list = list(tasks)
    sid_usage = Counter(task.sid for task in task_list)
    reserved_paths: set[Path] = set()
    used_source_paths: set[Path] = set()
    signature_cache: dict[Path, tuple[int, str]] = {}

    report: dict[str, object] = {
        "duplicate_mode": duplicate_mode,
        "conflict_mode": conflict_mode,
        "dry_run": dry_run,
        "total_tasks": len(task_list),
        "labeled": 0,
        "missing_sources": 0,
        "ambiguous_sources": 0,
        "resolved_by_bank": 0,
        "resolved_by_global_unique": 0,
        "destination_conflicts": 0,
        "copied": 0,
        "moved": 0,
        "linked": 0,
        "link_fallback_copies": 0,
        "skipped_existing": 0,
        "indexed_files": len(source_index.all_files),
        "indexed_ids": len(source_index.by_sid),
        "unused_source_files": 0,
    }

    for task in task_list:
        source_candidate, resolution = _resolve_source(
            task, source_index, signature_cache
        )
        if source_candidate is None and resolution == "missing":
            report["missing_sources"] += 1
            print(f"⚠  missing source for SID {task.sid} -> {task.dst.name}")
            continue
        if source_candidate is None and resolution == "ambiguous":
            report["ambiguous_sources"] += 1
            print(f"⚠  ambiguous source for SID {task.sid} -> {task.dst.name}")
            continue

        assert source_candidate is not None
        src = source_candidate.path
        used_source_paths.add(src)
        if resolution == "bank":
            report["resolved_by_bank"] += 1
        else:
            report["resolved_by_global_unique"] += 1

        dst, had_conflict = _resolve_conflict(src, task.dst, reserved_paths, conflict_mode)
        if had_conflict:
            report["destination_conflicts"] += 1
        reserved_paths.add(dst)

        if src.resolve() == dst.resolve() or _same_file_content(src, dst):
            report["skipped_existing"] += 1
            report["labeled"] += 1
            continue

        effective_mode = _select_mode(duplicate_mode, sid_usage[task.sid])

        if dry_run:
            if effective_mode == "move":
                report["moved"] += 1
            elif effective_mode == "link":
                report["linked"] += 1
            else:
                report["copied"] += 1
            report["labeled"] += 1
            continue

        dst.parent.mkdir(parents=True, exist_ok=True)

        if effective_mode == "move":
            shutil.move(src, dst)
            report["moved"] += 1
        elif effective_mode == "link":
            try:
                os.link(src, dst)
                report["linked"] += 1
            except OSError:
                shutil.copy2(src, dst)
                report["copied"] += 1
                report["link_fallback_copies"] += 1
        else:
            shutil.copy2(src, dst)
            report["copied"] += 1
        report["labeled"] += 1

    report["unused_source_files"] = len(set(source_index.all_files) - used_source_paths)

    return report


def categorise_wems(
    wiki_root: Path,
    src_dir: Path,
    dst_root: Path,
    src_suffix: str = ".wem.wav",
    dst_suffix: str = ".wav",
    duplicate_mode: str = "copy",
    conflict_mode: str = "suffix",
    dry_run: bool = False,
) -> dict[str, object]:
    """Organize WAVs into folders/names by SID-wiki definitions.

    Args:
        wiki_root: Folder with SID-wiki markdown.
        src_dir: Directory recursively searched for source WAV files.
        dst_root: Output directory for labeled folder tree.
        src_suffix: Source file extension.
        dst_suffix: Destination file extension.
        duplicate_mode: ``copy`` | ``move`` | ``link``.
        conflict_mode: Conflict strategy; currently only ``suffix``.
        dry_run: Build a plan without mutating files.

    Returns:
        Summary report of planned/applied operations.
    """
    if duplicate_mode not in {"copy", "move", "link"}:
        raise ValueError(
            f"Invalid duplicate_mode={duplicate_mode!r}; expected copy|move|link"
        )
    if conflict_mode not in {"suffix"}:
        raise ValueError(
            f"Invalid conflict_mode={conflict_mode!r}; expected suffix"
        )
    if not wiki_root.exists() or not wiki_root.is_dir():
        raise FileNotFoundError(f"Wiki root not found: {wiki_root}")
    if not src_dir.exists() or not src_dir.is_dir():
        raise FileNotFoundError(f"Source directory not found: {src_dir}")

    source_index = build_source_index(src_dir, src_suffix)
    tasks = build_tasks(wiki_root, dst_root, dst_suffix)
    report = materialise(tasks, source_index, duplicate_mode, conflict_mode, dry_run)
    report["source_root"] = str(src_dir)
    report["destination_root"] = str(dst_root)
    report["wiki_root"] = str(wiki_root)
    report["source_root_missing"] = False
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Organize BG3 WAVs using SID-wiki tables"
    )
    parser.add_argument(
        "--src",
        type=Path,
        default=Path("."),
        help="Source folder (flat or semi-sorted). Default: current directory.",
    )
    parser.add_argument(
        "--dst",
        type=Path,
        default=None,
        help="Output root folder. Default: --src (in-place).",
    )
    parser.add_argument(
        "--wiki",
        type=Path,
        default=Path(os.getenv("SIDS_WIKI", "bg3-sids.wiki")),
        help="SID-wiki markdown folder. Default: env SIDS_WIKI or ./bg3-sids.wiki",
    )
    parser.add_argument("--src-suffix", default=".wem.wav")
    parser.add_argument("--dst-suffix", default=".wav")
    parser.add_argument(
        "--duplicate-mode",
        choices=["copy", "move", "link"],
        default="copy",
        help="How to handle reused SIDs. Default: copy.",
    )
    parser.add_argument(
        "--conflict-mode",
        choices=["suffix"],
        default="suffix",
        help="How to resolve filename collisions. Default: suffix.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan operations without mutating files.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Optional JSON report file path.",
    )
    return parser.parse_args()


def _write_report(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _cli() -> None:
    args = _parse_args()
    dst_root = args.dst or args.src

    try:
        report = categorise_wems(
            wiki_root=args.wiki,
            src_dir=args.src,
            dst_root=dst_root,
            src_suffix=args.src_suffix,
            dst_suffix=args.dst_suffix,
            duplicate_mode=args.duplicate_mode,
            conflict_mode=args.conflict_mode,
            dry_run=args.dry_run,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"[label-error] {exc}") from exc

    if args.report is not None:
        _write_report(args.report, report)
        print(f"Report written: {args.report}")

    print("Auto-labeling complete.")


if __name__ == "__main__":
    _cli()
