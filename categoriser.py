"""BG3 audio-asset workflow.

Copy `.env.example` to `.env`, set absolute paths, then:

    pip install -r requirements.txt  # plus python-dotenv for .env loading
    python categoriser.py

Workflow
--------
1. Convert all *.wem* → *.wav* with vgmstream-cli.
2. Decode *.bnk* archives to XML with wwiser.py.
3. Group WAVs into folders that match their parent bank.
4. Rename WAVs with human-friendly names from the SID-wiki markdown.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Iterable, Iterator

try:                       # optional convenience
    from dotenv import load_dotenv
    load_dotenv()          # loads .env into os.environ
except ModuleNotFoundError:
    pass


def env_path(key: str) -> Path:
    """Return an absolute path from ``key`` or abort with a clear error.

    Args:
        key: Environment-variable name to look up.

    Returns:
        Path resolved from the value of *key*.

    Raises:
        SystemExit: If the variable is missing or empty.
    """
    value = os.getenv(key)
    if not value:
        sys.exit(f"[env-error] Define {key} in .env (see .env.example).")
    return Path(value)


WWISER_PY = env_path("WWISER_PY")
VGMSTREAM_DIR = env_path("VGMSTREAM_DIR")
UNPACKED_DATA = env_path("UNPACKED_DATA")
AUDIO_CONVERTED = env_path("AUDIO_CONVERTED")
SIDS_WIKI = env_path("SIDS_WIKI")

PROGRESS_BAR_MODE = os.getenv("PROGRESS_BAR_MODE", "auto").lower()

SHOULD_CONVERT = True
SHOULD_DECODE_BANKS = True
SHOULD_GROUP = True
SHOULD_RENAME = True


def progress_bar() -> Callable[[Iterable],
                               Iterator[tuple[int, int, object]]]:
    """Pick the best progress-bar generator available.

    Returns:
        A generator that yields ``(index, total, item)`` and updates
        a visual progress bar (alive-progress or plain stdout).
    """

    def basic(items: Iterable) -> Iterator[tuple[int, int, object]]:
        items = list(items)
        total = len(items)
        for idx, item in enumerate(items, 1):
            print(f"\r  {idx}/{total}", end="", flush=True)
            yield idx, total, item
        print()

    try:
        if PROGRESS_BAR_MODE in {"auto", "alive"}:
            import alive_progress  # type: ignore

            def alive(items: Iterable) -> Iterator[tuple[int, int, object]]:
                seq = list(items)
                total = len(seq)
                with alive_progress.alive_bar(total) as bar:
                    for idx, item in enumerate(seq, 1):
                        yield idx, total, item
                        bar()

            return alive
    except ModuleNotFoundError:
        pass
    return basic


bar = progress_bar()


def vgmstream_cli() -> Path:
    """Return an executable path to ``vgmstream-cli``.

    Ensures the binary is present and, on Unix, has its execute bit set.

    Returns:
        Absolute path to *vgmstream-cli*.

    Raises:
        SystemExit: If the binary is missing or lacks execute permissions.
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
    """Convert every *.wem* in *src* to WAV in *dst*.

    Args:
        src: Directory containing the original WEM files.
        dst: Directory to receive the converted WAV files.
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
    """Decode every *.bnk* in *src* to XML via wwiser.py.

    Args:
        src: Directory containing BNK bank files.
    """
    for _, _, bank in bar(src.glob("*.bnk")):
        subprocess.run(
            [sys.executable, WWISER_PY, "-d", "xsl", bank],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def create_bank_folders(banks: Path, sounds: Path) -> None:
    """Group WAVs into folders named after their parent bank.

    Args:
        banks: Folder containing *.bnk.xml* metadata.
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


def sid_mapping(md: Path) -> dict[str, str]:
    """Build a mapping from sound-ID to descriptive filename.

    Args:
        md: Markdown file containing the SID table.

    Returns:
        Dictionary {sound_id: descriptive_name}.
    """
    mapping: dict[str, str] = {}
    with md.open() as fh:
        for line in fh:
            m = re.match(r"^\| \d+ \| (\w+) \| (.*) \|$", line)
            if m:
                base = m.group(1)
                for idx, sid in enumerate(m.group(2).split(", ")):
                    mapping[sid] = f"{base}_{idx}"
    return mapping


def rename_files(root: Path) -> None:
    """Rename WAVs in *root* using SID wiki mappings.

    Args:
        root: Top-level folder containing bank sub-folders of WAVs.
    """
    md_files = list(SIDS_WIKI.glob("*.bnk.md"))
    for _, _, folder in bar(p for p in root.iterdir() if p.is_dir()):
        md = next((m for m in md_files if folder.name in m.name), None)
        if not md:
            print(f"  ✗ No mapping for {folder.name}")
            continue
        if md.name == "Amb_[PAK]_Amb_Ps_Specific-_-AMB_PS_SPECIFIC.bnk.md":
            md = (SIDS_WIKI /
                  "Ambience_[PAK]_Amb_Ps_Specific-_-AMB_PS_SPECIFIC.bnk.md")
        names = sid_mapping(md)
        for sound in folder.glob("*.wem.wav"):
            sid = sound.stem.split(".")[0]
            if sid in names:
                sound.rename(folder / f"{names[sid]}.wav")


def ensure_dirs(*paths: Path) -> None:
    """Create directories (and parents) if they do not yet exist."""
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def main() -> None:  # noqa: C901 (CLI complexity)
    """Orchestrate the four pipeline stages."""
    src_sound = UNPACKED_DATA / "SharedSounds/Public/Shared/Assets/Sound"
    src_sound_dev = (UNPACKED_DATA /
                     "SharedSounds/Public/SharedDev/Assets/Sound")
    src_banks = UNPACKED_DATA / "SharedSoundBanks/Public/Shared/Assets/Sound"
    src_banks_dev = (UNPACKED_DATA /
                     "SharedSoundBanks/Public/SharedDev/Assets/Sound")

    dst_sound = AUDIO_CONVERTED / "Shared"
    dst_sound_dev = AUDIO_CONVERTED / "SharedDev"

    ensure_dirs(src_sound, src_sound_dev, src_banks, src_banks_dev,
                dst_sound, dst_sound_dev)

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
        create_bank_folders(src_banks, dst_sound)
        print("  SharedDev")
        create_bank_folders(src_banks_dev, dst_sound_dev)

    if SHOULD_RENAME:
        print("Renaming files\n  Shared")
        rename_files(dst_sound)
        print("  SharedDev")
        rename_files(dst_sound_dev)

    print("Done")


if __name__ == "__main__":
    main()
