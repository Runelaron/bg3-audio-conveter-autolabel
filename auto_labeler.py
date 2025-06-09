"""Organise BG3 WAV files into SID-wiki based folder trees.

Rules
-----
• A *main* folder is created per markdown file (its stem).  
• If a table row lists **multiple** WEM-IDs:
      <md_stem>/<row_name>/1.wav, 2.wav, …  
• If a row lists **one** WEM-ID:
      <md_stem>/<row_name>.wav   (no extra sub-folder)

Invalid path characters (slash, backslash, colon, etc.) are replaced by “_”.
"""

from __future__ import annotations

import re
import shutil
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, List


@dataclass
class MoveTask:
    """File-move specification."""
    src: Path
    dst: Path


SAFE_CHARS = f"-_. {string.ascii_letters}{string.digits}"


def _safe(name: str) -> str:
    """Return *name* with OS-unsafe chars replaced by “_”."""
    return "".join(ch if ch in SAFE_CHARS else "_" for ch in name)


def parse_markdown(md: Path) -> Iterable[tuple[str, List[str]]]:
    """Yield ``(row_name, [wem_id, …])`` pairs for each table row.

    Args:
        md: Markdown file containing a three-column SID table.

    Yields:
        Row name and list of WEM-ID strings.
    """
    row = re.compile(r"^\|\s*\d+\s*\|\s*([^|]+?)\s*\|\s*([0-9, ]+)\s*\|")
    with md.open() as fh:
        for line in fh:
            if m := row.match(line):
                name = _safe(m.group(1).strip())
                ids = [tok.strip() for tok in m.group(2).split(",")]
                yield name, ids


def build_tasks(
    wiki_root: Path,
    src_dir: Path,
    dst_root: Path,
    src_suffix: str = ".wem.wav",
    dst_suffix: str = ".wav",
) -> Iterator[MoveTask]:
    """Generate a MoveTask for every WEM-ID referenced by the wiki.

    Args:
        wiki_root: Directory containing SID-wiki markdown files.
        src_dir: Folder with flat ``<wem_id><src_suffix>`` files.
        dst_root: Destination root for organised folders.
        src_suffix: Extension of source files.
        dst_suffix: Extension of renamed files.

    Yields:
        MoveTask objects.
    """
    for md in wiki_root.rglob("*.md"):
        top = dst_root / _safe(md.stem)
        for row_name, ids in parse_markdown(md):
            if len(ids) == 1:                                           # single ID
                wem_id = ids[0]
                src = src_dir / f"{wem_id}{src_suffix}"
                dst = top / f"{row_name}{dst_suffix}"
                yield MoveTask(src, dst)
            else:                                                       # multiple IDs
                leaf = top / row_name
                for idx, wem_id in enumerate(ids, 1):
                    src = src_dir / f"{wem_id}{src_suffix}"
                    dst = leaf / f"{idx}{dst_suffix}"
                    yield MoveTask(src, dst)


def materialise(tasks: Iterable[MoveTask]) -> None:
    """Create destination folders and move files.

    Args:
        tasks: Iterable of MoveTask items.
    """
    for task in tasks:
        task.dst.parent.mkdir(parents=True, exist_ok=True)
        if task.src.exists():
            shutil.move(task.src, task.dst)
        else:
            print(f"⚠ missing {task.src.name}")


def categorise_wems(wiki_root: Path, src_dir: Path, dst_root: Path) -> None:
    """High-level helper to organise WAVs according to the SID wiki.

    Args:
        wiki_root: Root folder of SID-wiki markdown files.
        src_dir: Directory of flat WAVs (``<id>.wem.wav`` files).
        dst_root: Destination root for organised folders.
    """
    tasks = build_tasks(wiki_root, src_dir, dst_root)
    materialise(tasks)
