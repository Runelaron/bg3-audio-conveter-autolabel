"""Utilities to organise BG3 WEM files by SID-wiki tables."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, List


@dataclass
class MoveTask:
    """Single file-move operation."""
    src: Path
    dst: Path


def parse_markdown(md: Path) -> Iterable[tuple[str, List[str]]]:
    """Extract table rows from *md*.

    Args:
        md: Markdown file that contains a three-column SID table.

    Yields:
        Tuples ``(row_name, [wem_id, …])`` for each table row.
    """
    row = re.compile(r"^\|\s*\d+\s*\|\s*([^|]+)\s*\|\s*([0-9, ]+)\s*\|")
    with md.open() as fh:
        for line in fh:
            if m := row.match(line):
                name = m.group(1).strip()
                ids = [tok.strip() for tok in m.group(2).split(",")]
                yield name, ids


def build_tasks(
    wiki_root: Path,
    src_dir: Path,
    dst_root: Path,
    src_suffix: str = ".wem.wav",
    dst_suffix: str = ".wav",
) -> Iterator[MoveTask]:
    """Create a MoveTask for every WEM ID found under *wiki_root*.

    Args:
        wiki_root: Directory containing *.md* SID tables.
        src_dir: Folder with flat ``<wem_id>.wem.wav`` files.
        dst_root: Destination root for organised folders.
        src_suffix: Suffix of source files.
        dst_suffix: Suffix for renamed files.

    Yields:
        A sequence of MoveTask objects.
    """
    for md in wiki_root.rglob("*.md"):
        top = dst_root / md.stem
        for row_name, ids in parse_markdown(md):
            leaf = top / row_name
            for idx, wem_id in enumerate(ids, 1):
                src = src_dir / f"{wem_id}{src_suffix}"
                dst = leaf / f"{idx}{dst_suffix}"
                yield MoveTask(src, dst)


def materialise(tasks: Iterable[MoveTask]) -> None:
    """Create destination folders and perform all moves.

    Args:
        tasks: Iterable of MoveTask items.
    """
    for task in tasks:
        task.dst.parent.mkdir(parents=True, exist_ok=True)
        if task.src.exists():
            shutil.move(task.src, task.dst)
        else:
            print(f"⚠ missing {task.src.name}")


def categorise_wems(
    wiki_root: Path,
    src_dir: Path,
    dst_root: Path,
) -> None:
    """End-to-end workflow: build tasks, then move files.

    Args:
        wiki_root: Root folder containing SID-wiki markdown files.
        src_dir: Directory with flat WEM WAV files.
        dst_root: Destination root for organised folders.
    """
    tasks = build_tasks(wiki_root, src_dir, dst_root)
    materialise(tasks)
