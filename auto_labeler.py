"""Organize BG3 WAV files into SID-wiki-based folder structures.

Can be imported (`categorise_wems`) or run as a script (see --help).
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, List, Optional


@dataclass
class MoveTask:
    """Specifies a file move from src to dst."""
    src: Optional[Path]
    dst: Path


SAFE_CHARS = f"-_. {string.ascii_letters}{string.digits}"


def _safe(text: str) -> str:
    """Replace unsafe filesystem chars in *text* with underscores."""
    return "".join(ch if ch in SAFE_CHARS else "_" for ch in text)


def parse_markdown(md: Path) -> Iterable[tuple[str, List[str]]]:
    """Yield (row_name, wem_ids) for each row in SID-wiki markdown.

    Args:
        md: Markdown file with a SID table.

    Yields:
        Tuples of cleaned row name and a list of WEM ID strings.
    """
    pat = re.compile(r"^\|\s*\d+\s*\|\s*([^|]+?)\s*\|\s*([0-9, ]+)\s*\|")
    with md.open() as fh:
        for line in fh:
            if m := pat.match(line):
                name = _safe(m.group(1).strip())
                ids = [s.strip() for s in m.group(2).split(",")]
                yield name, ids


def find_wem(src_root: Path, wem_id: str, suffix: str) -> Optional[Path]:
    """Find first file matching wem_id under src_root, searching recursively.

    Args:
        src_root: Directory to search.
        wem_id: WEM ID as string.
        suffix: File extension (e.g. '.wem.wav').

    Returns:
        Path to first match, or None if not found.
    """
    pattern = f"{wem_id}{suffix}"
    return next(src_root.rglob(pattern), None)


def build_tasks(
    wiki_root: Path,
    src_dir: Path,
    dst_root: Path,
    src_suffix: str = ".wem.wav",
    dst_suffix: str = ".wav",
) -> Iterator[MoveTask]:
    """Generate a MoveTask for every WEM ID found in the SID-wiki.

    Args:
        wiki_root: Root directory of SID-wiki markdown files.
        src_dir: Directory (recursively searched) for source WAVs.
        dst_root: Where to build the destination folder tree.
        src_suffix: File extension of source files.
        dst_suffix: File extension for renamed/moved files.

    Yields:
        MoveTask objects for each move.
    """
    for md in wiki_root.rglob("*.md"):
        top = dst_root / _safe(md.stem)
        for row_name, ids in parse_markdown(md):
            if len(ids) == 1:
                wem_id = ids[0]
                src = find_wem(src_dir, wem_id, src_suffix)
                dst = top / f"{row_name}{dst_suffix}"
                yield MoveTask(src, dst)
            else:
                leaf = top / row_name
                for idx, wem_id in enumerate(ids, 1):
                    src = find_wem(src_dir, wem_id, src_suffix)
                    dst = leaf / f"{idx}{dst_suffix}"
                    yield MoveTask(src, dst)


def materialise(tasks: Iterable[MoveTask]) -> None:
    """Create needed folders and move WAV files as specified.

    Args:
        tasks: Iterable of MoveTask objects.
    """
    for task in tasks:
        task.dst.parent.mkdir(parents=True, exist_ok=True)
        if task.src and task.src.exists():
            shutil.move(task.src, task.dst)
        else:
            print(f"⚠  missing source for {task.dst.name}")


def categorise_wems(
    wiki_root: Path,
    src_dir: Path,
    dst_root: Path,
    src_suffix: str = ".wem.wav",
    dst_suffix: str = ".wav",
) -> None:
    """Organize WAVs into folders/names by SID-wiki definitions.

    Args:
        wiki_root: Folder with SID-wiki markdown.
        src_dir: Flat or semi-sorted WAV input directory.
        dst_root: Output directory for labeled/organized tree.
        src_suffix: Source file extension.
        dst_suffix: Destination file extension.
    """
    tasks = build_tasks(wiki_root, src_dir, dst_root, src_suffix, dst_suffix)
    materialise(tasks)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Organize BG3 WAVs using SID-wiki tables"
    )
    parser.add_argument(
        "--src", type=Path, default=Path("."),
        help="Source folder (flat or semi-sorted). Default: current directory."
    )
    parser.add_argument(
        "--dst", type=Path, default=None,
        help="Output root folder. Default: --src (in-place)."
    )
    parser.add_argument(
        "--wiki", type=Path,
        default=Path(os.getenv("SIDS_WIKI", "bg3-sids.wiki")),
        help="SID-wiki markdown folder. Default: env SIDS_WIKI or ./bg3-sids.wiki"
    )
    parser.add_argument("--src-suffix", default=".wem.wav")
    parser.add_argument("--dst-suffix", default=".wav")
    return parser.parse_args()


def _cli() -> None:
    args = _parse_args()
    dst_root = args.dst or args.src
    categorise_wems(
        wiki_root=args.wiki,
        src_dir=args.src,
        dst_root=dst_root,
        src_suffix=args.src_suffix,
        dst_suffix=args.dst_suffix,
    )
    print("Auto-labeling complete.")


if __name__ == "__main__":
    _cli()
