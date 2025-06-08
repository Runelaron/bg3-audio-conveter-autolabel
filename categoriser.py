"""BG3 audio asset tools: Convert, decode, group, and rename Wwise files."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

WWISER_PY = Path("/home/rune/code/bg3/wwiser/wwiser.py")
VGMSTREAM_DIR = Path("/home/rune/code/bg3/vgmstream")
UNPACKED_DATA = Path("/home/rune/code/bg3/sounds/UnpackedData")
AUDIO_CONVERTED = Path("/home/rune/code/bg3/sounds/converted")
SIDS_WIKI = Path("/home/rune/code/bg3/bg3-sids.wiki")

SHOULD_CONVERT = True
SHOULD_DECODE_BANKS = True
SHOULD_GROUP = True
SHOULD_RENAME = True


def progress(items: Iterable[Path]) -> Iterable[tuple[int, int, Path]]:
    """Yield (idx, total, item) and print a progress counter."""
    items = list(items)
    total = len(items)
    for idx, item in enumerate(items, 1):
        print(f"\r  {idx}/{total}", end="", flush=True)
        yield idx, total, item
    print()


def vgmstream_exe() -> Path:
    """Return path to vgmstream-cli, ensuring it is executable."""
    exe_name = "vgmstream-cli.exe" if os.name == "nt" else "vgmstream-cli"
    exe = VGMSTREAM_DIR / exe_name
    if not exe.exists():
        raise FileNotFoundError(f"{exe} not found. Build or install vgmstream.")
    if os.name != "nt" and not os.access(exe, os.X_OK):
        try:
            exe.chmod(exe.stat().st_mode | 0o111)
        except PermissionError as err:
            raise PermissionError(
                f"{exe} exists but is not executable. "
                "Run `chmod +x` or move it off NTFS."
            ) from err
    return exe


def convert_wem_folder(src: Path, dst: Path) -> None:
    """Convert all *.wem files in src to WAV files in dst."""
    cli = vgmstream_exe()
    for _, _, wem in progress(src.glob("*.wem")):
        out_file = dst / f"{wem.name}.wav"
        subprocess.run(
            [cli, "-o", out_file, wem],
            check=True,
            cwd=VGMSTREAM_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def decode_banks(src: Path) -> None:
    """Run wwiser.py on each *.bnk in src to produce XML metadata."""
    for _, _, bank in progress(src.glob("*.bnk")):
        subprocess.run(
            [sys.executable, WWISER_PY, "-d", "xsl", bank],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def create_banks_folders(banks_dir: Path, sounds_dir: Path) -> None:
    """Move WAVs into subfolders named after their parent bank."""
    for _, _, xml in progress(banks_dir.glob("*.bnk.xml")):
        bank_folder = sounds_dir / xml.stem
        bank_folder.mkdir(exist_ok=True)
        with xml.open() as fh:
            for line in fh:
                if 'name="sourceID"' not in line:
                    continue
                sound_id = line.split('"')[-2]
                src = sounds_dir / f"{sound_id}.wem.wav"
                if src.exists():
                    shutil.move(src, bank_folder / src.name)


def sid_mapping(markdown: Path) -> dict[str, str]:
    """Return {sound_id: new_name} mapping from a SID wiki markdown file."""
    mapping: dict[str, str] = {}
    with markdown.open() as fh:
        for line in fh:
            m = re.match(r"^\| \d+ \| (\w+) \| (.*) \|$", line)
            if not m:
                continue
            base = m.group(1)
            for idx, sid in enumerate(m.group(2).split(", ")):
                mapping[sid] = f"{base}_{idx}"
    return mapping


def rename_files(root: Path) -> None:
    """Rename *.wem.wav files using human-friendly names from SID wiki."""
    md_files = list(SIDS_WIKI.glob("*.bnk.md"))
    for _, _, folder in progress(p for p in root.iterdir() if p.is_dir()):
        md = next(
            (
                m for m in md_files
                if f"{folder.name}-" in m.name or f"{folder.name}.bnk.md" in m.name
            ),
            None,
        )
        if md is None:
            print(f"  ✗ No mappings for {folder.name}")
            continue
        # Special-case file fix from original script
        if md.name == "Amb_[PAK]_Amb_Ps_Specific-_-AMB_PS_SPECIFIC.bnk.md":
            md = SIDS_WIKI / "Ambience_[PAK]_Amb_Ps_Specific-_-AMB_PS_SPECIFIC.bnk.md"
        id_map = sid_mapping(md)
        for sound in folder.glob("*.wem.wav"):
            sid = sound.stem.split(".")[0]
            if sid in id_map:
                sound.rename(folder / f"{id_map[sid]}.wav")


def ensure_dirs(*paths: Path) -> None:
    """Create each directory (with parents) if it does not exist."""
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def main() -> None:
    """Run the asset conversion pipeline."""
    src_sound = UNPACKED_DATA / "SharedSounds" / "Public" / "Shared" / "Assets" / "Sound"
    src_sound_dev = UNPACKED_DATA / "SharedSounds" / "Public" / "SharedDev" / "Assets" / "Sound"
    src_banks = UNPACKED_DATA / "SharedSoundBanks" / "Public" / "Shared" / "Assets" / "Sound"
    src_banks_dev = UNPACKED_DATA / "SharedSoundBanks" / "Public" / "SharedDev" / "Assets" / "Sound"

    dst_sound = AUDIO_CONVERTED / "Shared"
    dst_sound_dev = AUDIO_CONVERTED / "SharedDev"

    ensure_dirs(
        src_sound, src_sound_dev, src_banks, src_banks_dev,
        dst_sound, dst_sound_dev,
    )

    if SHOULD_CONVERT:
        print("Converting sound files\n  Shared")
        convert_wem_folder(src_sound, dst_sound)
        print("  SharedDev")
        convert_wem_folder(src_sound_dev, dst_sound_dev)

    if SHOULD_DECODE_BANKS:
        print("Decoding sound banks\n  Shared")
        decode_banks(src_banks)
        print("  SharedDev")
        decode_banks(src_banks_dev)

    if SHOULD_GROUP:
        print("Grouping files by bank\n  Shared")
        create_banks_folders(src_banks, dst_sound)
        print("  SharedDev")
        create_banks_folders(src_banks_dev, dst_sound_dev)

    if SHOULD_RENAME:
        print("Renaming files\n  Shared")
        rename_files(dst_sound)
        print("  SharedDev")
        rename_files(dst_sound_dev)

    print("Done")


if __name__ == "__main__":
    main()
