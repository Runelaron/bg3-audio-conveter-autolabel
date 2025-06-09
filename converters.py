"""Low-level helpers: WEM → WAV conversion and bank grouping."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from config import VGMSTREAM_DIR, WWISER_PY
from progress import bar


def vgmstream_cli() -> Path:
    """Return a usable path to *vgmstream-cli*.

    Returns:
        Absolute Path to the binary.

    Raises:
        SystemExit: If the binary is missing or non-executable.
    """
    exe = VGMSTREAM_DIR / ("vgmstream-cli.exe" if os.name == "nt"
                           else "vgmstream-cli")
    if not exe.exists():
        sys.exit("[env-error] vgmstream-cli not found in VGMSTREAM_DIR.")
    if os.name != "nt" and not os.access(exe, os.X_OK):
        try:
            exe.chmod(exe.stat().st_mode | 0o111)
        except PermissionError as exc:
            sys.exit(f"[perm-error] Cannot mark {exe} executable: {exc}")
    return exe


def convert_wem_folder(src: Path, dst: Path) -> None:
    """Convert each ``*.wem`` in *src* to ``*.wav`` in *dst*.

    Args:
        src: Folder containing WEM files.
        dst: Destination folder for WAV files.
    """
    cli = vgmstream_cli()
    for _, _, wem in bar(src.glob("*.wem")):
        out_file = dst / f"{wem.name}.wav"
        subprocess.run(
            [cli, "-o", out_file, wem],
            check=True,
            cwd=VGMSTREAM_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def decode_banks(src: Path) -> None:
    """Run wwiser.py on each ``*.bnk`` to produce XML metadata.

    Args:
        src: Folder containing BNK bank files.
    """
    for _, _, bank in bar(src.glob("*.bnk")):
        subprocess.run(
            [sys.executable, WWISER_PY, "-d", "xsl", bank],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def create_bank_folders(banks: Path, sounds: Path) -> None:
    """Group WAVs into per-bank subfolders.

    Args:
        banks: Directory with ``*.bnk.xml`` metadata files.
        sounds: Folder where flat WAVs currently reside.
    """
    for _, _, xml in bar(banks.glob("*.bnk.xml")):
        folder = sounds / xml.stem
        folder.mkdir(exist_ok=True)
        with xml.open() as fh:
            for line in fh:
                if 'name="sourceID"' in line:
                    sid = line.split('"')[-2]
                    src = sounds / f"{sid}.wem.wav"
                    if src.exists():
                        shutil.move(src, folder / src.name)
