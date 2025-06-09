"""Organise WAV files into SID-wiki-based folder structures."""

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
    """Extract ``(row_name, [wem_id, …])`` pairs from a SID table.

    Args:
        md: Markdown file containing the table.

    Yields:
        Each table row’s *Name* and a list of WEM-ID strings.
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
    """Generate MoveTask objects for every WEM ID listed in the wiki.

    Args:
        wiki_root: Root directory containing SID-wiki markdown files.
        src_dir: Folder with flat ``<wem_id><src_suffix>`` files.
        dst_root: Destination root for the organised tree.
        src_suffix: Extension of source files.
        dst_suffix: Extension for renamed files.

    Yields:
        MoveTask objects describing each pending copy/move.
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
    """Create folders and move each file.

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
    """High-level helper: build tasks then move files.

    Args:
        wiki_root: Root folder of SID-wiki markdown files.
        src_dir: Folder of flat WAVs (``<id>.wem.wav``).
        dst_root: Root of organised folder tree.
    """
    tasks = build_tasks(wiki_root, src_dir, dst_root)
    materialise(tasks)
