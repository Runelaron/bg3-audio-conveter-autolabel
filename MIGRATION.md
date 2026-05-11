# Migration Notes

## From Old Workflow (`categoriser.py`) to Current Workflow (`main.py`)

Legacy instructions referenced editing constants in `categoriser.py` and running:

```sh
python categoriser.py
```

Current workflow uses environment configuration and `main.py`:

```sh
python3 main.py
```

## Mapping

- `wwiser_pyz` -> `WWISER_PY`
- `folder_vgmstream` -> `VGMSTREAM_DIR`
- `folder_unpacked_data` -> `UNPACKED_DATA`
- `folder_audio_converted` -> `AUDIO_CONVERTED`
- `folder_bg3sids_wiki` -> `SIDS_WIKI`
- labeled output root -> `AUDIO_LABELED` (optional)
- strict audit mode -> `BG3_LABEL_STRICT` (optional)
- consolidated label JSON report -> `BG3_LABEL_REPORT` (optional)

## Stage Toggles

Instead of editing booleans in code, use env flags:

- `BG3_CONVERT`
- `BG3_DECODE_BANKS`
- `BG3_GROUP_BY_BANK`
- `BG3_SORT_BY_SID`

Example (label-only run):

```sh
BG3_CONVERT=0 BG3_DECODE_BANKS=0 BG3_GROUP_BY_BANK=0 BG3_SORT_BY_SID=1 python3 main.py
```

Example (strict label audit with JSON report):

```sh
BG3_CONVERT=0 BG3_DECODE_BANKS=0 BG3_GROUP_BY_BANK=0 BG3_SORT_BY_SID=1 \
BG3_LABEL_STRICT=1 \
BG3_LABEL_REPORT=/tmp/bg3-label-report.json \
python3 main.py
```

## Auto-Labeler Behavior Changes

- Duplicate SID mappings now default to `copy` semantics to avoid losing later mappings.
- Output conflict handling defaults to suffixing (`_2`, `_3`, ...).
- `--dry-run` and `--report` are available in `auto_labeler.py` CLI.
- Labeling is bank-aware: matching bank folders win over global SID fallback.
- Runs can now report missing roots, missing sources, ambiguous sources, and unused source files.
