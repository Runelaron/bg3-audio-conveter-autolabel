"""Entry point for the BG3 audio-asset pipeline.

Env flags (“0”, “false”, “no”, or an empty string → off):

    BG3_CONVERT          convert *.wem → *.wav*
    BG3_DECODE_BANKS     run wwiser.py on *.bnk*
    BG3_GROUP_BY_BANK    move WAVs into per-bank folders
    BG3_SORT_BY_SID      organise/rename via SID-wiki tables
"""

from __future__ import annotations

import os
from pathlib import Path

from auto_labeler import categorise_wems
from config import AUDIO_CONVERTED, UNPACKED_DATA
from converters import convert_wem_folder, create_bank_folders, decode_banks


def flag(env_var: str, default: bool = True) -> bool:
    """Interpret *env_var* as a boolean.

    Args:
        env_var: Name of the environment variable.
        default: Value when the variable is unset.

    Returns:
        ``False`` when the value is ``"", "0", "false", "no"`` (case-insensitive);
        ``True`` otherwise.
    """
    val = os.getenv(env_var, str(default))
    return val.strip().lower() not in {"", "0", "false", "no"}


SHOULD_CONVERT = flag("BG3_CONVERT", True)
SHOULD_DECODE = flag("BG3_DECODE_BANKS", True)
SHOULD_GROUP = flag("BG3_GROUP_BY_BANK", True)
SHOULD_SORT = flag("BG3_SORT_BY_SID", True)


def ensure_dirs(*paths: Path) -> None:
    """Create directories (and parents) if they do not yet exist."""
    for p in paths:
        p.mkdir(parents=True, exist_ok=True)


def main() -> None:  # noqa: C901
    """Execute the pipeline according to environment flags."""
    src_sound = UNPACKED_DATA / "SharedSounds/Public/Shared/Assets/Sound"
    src_sound_dev = (
        UNPACKED_DATA / "SharedSounds/Public/SharedDev/Assets/Sound"
    )
    src_banks = UNPACKED_DATA / "SharedSoundBanks/Public/Shared/Assets/Sound"
    src_banks_dev = (
        UNPACKED_DATA / "SharedSoundBanks/Public/SharedDev/Assets/Sound"
    )

    dst_sound = AUDIO_CONVERTED / "Shared"
    dst_sound_dev = AUDIO_CONVERTED / "SharedDev"

    ensure_dirs(
        src_sound,
        src_sound_dev,
        src_banks,
        src_banks_dev,
        dst_sound,
        dst_sound_dev,
    )

    if SHOULD_CONVERT:
        print("Converting sound files")
        print("  Shared")
        convert_wem_folder(src_sound, dst_sound)
        print("  SharedDev")
        convert_wem_folder(src_sound_dev, dst_sound_dev)

    if SHOULD_DECODE:
        print("Decoding sound banks")
        print("  Shared")
        decode_banks(src_banks)
        print("  SharedDev")
        decode_banks(src_banks_dev)

    if SHOULD_GROUP:
        print("Grouping files by bank")
        print("  Shared")
        create_bank_folders(src_banks, dst_sound)
        print("  SharedDev")
        create_bank_folders(src_banks_dev, dst_sound_dev)

    if SHOULD_SORT:
        sids_root = Path(os.getenv("SIDS_WIKI", "").strip())
        if not sids_root:
            print("⚠  SIDS_WIKI unset or empty; skipping SID sort")
        elif not sids_root.exists():
            print(f"⚠  SIDS_WIKI path {sids_root} not found; skipping")
        else:
            print("Organising WAVs via SID wiki")
            print("  Shared")
            categorise_wems(sids_root, dst_sound, dst_sound)
            print("  SharedDev")
            categorise_wems(sids_root, dst_sound_dev, dst_sound_dev)

    print("Done")


if __name__ == "__main__":
    main()
