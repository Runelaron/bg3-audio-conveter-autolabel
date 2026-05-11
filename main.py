"""Entry point for the BG3 audio-asset pipeline.

Env flags ("0", "false", "no", or empty string -> off):

    BG3_CONVERT          convert *.wem -> *.wav*
    BG3_DECODE_BANKS     run wwiser.py on *.bnk*
    BG3_GROUP_BY_BANK    move WAVs into per-bank folders
    BG3_SORT_BY_SID      organise/rename via SID-wiki tables
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from auto_labeler import categorise_wems
from config import (
    AUDIO_CONVERTED,
    AUDIO_LABELED,
    SIDS_WIKI,
    UNPACKED_DATA,
    require_env_path,
)
from converters import convert_wem_folder, create_bank_folders, decode_banks


def flag(env_var: str, default: bool = True) -> bool:
    """Interpret *env_var* as a boolean."""
    val = os.getenv(env_var, str(default))
    return val.strip().lower() not in {"", "0", "false", "no"}


SHOULD_CONVERT = flag("BG3_CONVERT", True)
SHOULD_DECODE = flag("BG3_DECODE_BANKS", True)
SHOULD_GROUP = flag("BG3_GROUP_BY_BANK", True)
SHOULD_SORT = flag("BG3_SORT_BY_SID", True)
LABEL_STRICT = flag("BG3_LABEL_STRICT", False)
LABEL_REPORT = os.getenv("BG3_LABEL_REPORT", "").strip()


def ensure_dirs(*paths: Path) -> None:
    """Create destination directories if needed."""
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def require_existing_dir(path: Path, label: str) -> None:
    """Abort when *path* does not exist as a directory."""
    if not path.exists() or not path.is_dir():
        sys.exit(f"[path-error] {label} directory not found: {path}")


def _empty_label_report(
    root_name: str,
    src_dir: Path,
    dst_dir: Path,
    reason: str,
) -> dict[str, object]:
    """Return a zero-work label report for an unavailable source root."""
    return {
        "root": root_name,
        "source_root": str(src_dir),
        "destination_root": str(dst_dir),
        "source_root_missing": True,
        "reason": reason,
        "duplicate_mode": "copy",
        "conflict_mode": "suffix",
        "dry_run": False,
        "total_tasks": 0,
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
        "indexed_files": 0,
        "indexed_ids": 0,
        "unused_source_files": 0,
    }


def _summarise_label_reports(
    root_reports: dict[str, dict[str, object]],
) -> dict[str, int | bool]:
    """Aggregate labeler reports across roots."""
    count_keys = (
        "total_tasks",
        "labeled",
        "missing_sources",
        "ambiguous_sources",
        "resolved_by_bank",
        "resolved_by_global_unique",
        "destination_conflicts",
        "copied",
        "moved",
        "linked",
        "link_fallback_copies",
        "skipped_existing",
        "indexed_files",
        "indexed_ids",
        "unused_source_files",
    )
    summary: dict[str, int | bool] = {key: 0 for key in count_keys}
    summary["missing_source_roots"] = 0

    for report in root_reports.values():
        if report.get("source_root_missing"):
            summary["missing_source_roots"] += 1
        for key in count_keys:
            summary[key] += int(report.get(key, 0))

    summary["strict"] = LABEL_STRICT
    summary["has_unresolved_labels"] = bool(
        summary["missing_source_roots"]
        or summary["missing_sources"]
        or summary["ambiguous_sources"]
    )
    return summary


def _print_label_summary(
    root_reports: dict[str, dict[str, object]],
    summary: dict[str, int | bool],
) -> None:
    """Print a compact label coverage summary."""
    print("Label coverage summary")
    for root_name, report in root_reports.items():
        if report.get("source_root_missing"):
            print(
                f"  {root_name}: source root missing"
                f" ({report['source_root']})"
            )
            continue
        print(
            "  "
            f"{root_name}: labeled={report['labeled']} "
            f"missing={report['missing_sources']} "
            f"ambiguous={report['ambiguous_sources']} "
            f"unused_source_files={report['unused_source_files']} "
            f"conflicts={report['destination_conflicts']}"
        )

    print(
        "  "
        f"Overall: labeled={summary['labeled']} "
        f"missing={summary['missing_sources']} "
        f"ambiguous={summary['ambiguous_sources']} "
        f"missing_roots={summary['missing_source_roots']} "
        f"unused_source_files={summary['unused_source_files']}"
    )


def _write_label_report(
    path: Path,
    root_reports: dict[str, dict[str, object]],
    summary: dict[str, int | bool],
) -> None:
    """Write the consolidated label report JSON file."""
    payload = {
        "strict": LABEL_STRICT,
        "summary": summary,
        "roots": root_reports,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    """Execute the pipeline according to environment flags."""
    needs_unpacked = SHOULD_CONVERT or SHOULD_DECODE or SHOULD_GROUP
    needs_converted_root = SHOULD_CONVERT or SHOULD_GROUP or SHOULD_SORT

    unpacked_data = (
        require_env_path("UNPACKED_DATA", UNPACKED_DATA)
        if needs_unpacked
        else (UNPACKED_DATA or Path("."))
    )
    audio_converted = (
        require_env_path("AUDIO_CONVERTED", AUDIO_CONVERTED)
        if needs_converted_root
        else (AUDIO_CONVERTED or Path("."))
    )
    sids_root = None
    if SHOULD_SORT:
        # Fail fast before running expensive earlier stages.
        sids_root = require_env_path("SIDS_WIKI", SIDS_WIKI)
        require_existing_dir(sids_root, "SID wiki")

    src_sound = unpacked_data / "SharedSounds/Public/Shared/Assets/Sound"
    src_sound_dev = unpacked_data / "SharedSounds/Public/SharedDev/Assets/Sound"
    src_banks = unpacked_data / "SharedSoundBanks/Public/Shared/Assets/Sound"
    src_banks_dev = unpacked_data / "SharedSoundBanks/Public/SharedDev/Assets/Sound"

    dst_sound = audio_converted / "Shared"
    dst_sound_dev = audio_converted / "SharedDev"

    if SHOULD_CONVERT:
        require_existing_dir(src_sound, "Shared source audio")
        require_existing_dir(src_sound_dev, "SharedDev source audio")
        ensure_dirs(dst_sound, dst_sound_dev)
        print("Converting sound files")
        print("  Shared")
        convert_wem_folder(src_sound, dst_sound)
        print("  SharedDev")
        convert_wem_folder(src_sound_dev, dst_sound_dev)

    if SHOULD_DECODE:
        require_existing_dir(src_banks, "Shared bank input")
        require_existing_dir(src_banks_dev, "SharedDev bank input")
        print("Decoding sound banks")
        print("  Shared")
        decode_banks(src_banks)
        print("  SharedDev")
        decode_banks(src_banks_dev)

    if SHOULD_GROUP:
        require_existing_dir(src_banks, "Shared decoded-bank input")
        require_existing_dir(src_banks_dev, "SharedDev decoded-bank input")
        ensure_dirs(dst_sound, dst_sound_dev)
        print("Grouping files by bank")
        print("  Shared")
        create_bank_folders(src_banks, dst_sound)
        print("  SharedDev")
        create_bank_folders(src_banks_dev, dst_sound_dev)

    if SHOULD_SORT:
        assert sids_root is not None
        labeled_root = AUDIO_LABELED or (audio_converted / "labeled")
        dst_labeled = labeled_root / "Shared"
        dst_labeled_dev = labeled_root / "SharedDev"
        root_reports: dict[str, dict[str, object]] = {}

        print("Organising WAVs via SID wiki")
        if not dst_sound.exists():
            print(f"  ⚠ Shared source folder missing, skipping: {dst_sound}")
            root_reports["Shared"] = _empty_label_report(
                "Shared",
                dst_sound,
                dst_labeled,
                "source root missing",
            )
        else:
            ensure_dirs(dst_labeled)
            print("  Shared")
            root_reports["Shared"] = categorise_wems(
                sids_root,
                dst_sound,
                dst_labeled,
                duplicate_mode="copy",
                conflict_mode="suffix",
                dry_run=False,
            )
            root_reports["Shared"]["root"] = "Shared"

        if not dst_sound_dev.exists():
            print(f"  ⚠ SharedDev source folder missing, skipping: {dst_sound_dev}")
            root_reports["SharedDev"] = _empty_label_report(
                "SharedDev",
                dst_sound_dev,
                dst_labeled_dev,
                "source root missing",
            )
        else:
            ensure_dirs(dst_labeled_dev)
            print("  SharedDev")
            root_reports["SharedDev"] = categorise_wems(
                sids_root,
                dst_sound_dev,
                dst_labeled_dev,
                duplicate_mode="copy",
                conflict_mode="suffix",
                dry_run=False,
            )
            root_reports["SharedDev"]["root"] = "SharedDev"

        summary = _summarise_label_reports(root_reports)
        _print_label_summary(root_reports, summary)

        if LABEL_REPORT:
            report_path = Path(LABEL_REPORT).expanduser()
            _write_label_report(report_path, root_reports, summary)
            print(f"Label report written: {report_path}")

        if LABEL_STRICT and summary["has_unresolved_labels"]:
            print("Strict label audit failed.")
            raise SystemExit(1)

    print("Done")


if __name__ == "__main__":
    main()
