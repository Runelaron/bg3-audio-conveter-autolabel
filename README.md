# BG3 Audio Converter + Auto Labeler

Cross-platform pipeline for processing Baldur's Gate 3 Wwise audio assets:

1. Convert `.wem` -> `.wav` via `vgmstream-cli`
2. Decode `.bnk` -> `.bnk.xml` via `wwiser.py`
3. Group converted WAV files by bank metadata
4. Build labeled output trees from `bg3-sids.wiki` mappings

The pipeline is controlled by environment variables and entrypoint `main.py`.

## Requirements

- Python 3.12+
- [BG3 Modders Multitool](https://github.com/ShinyHobo/BG3-Modders-Multitool) (for unpacked game assets)
- [vgmstream](https://github.com/vgmstream/vgmstream) (`vgmstream-cli`)
- [wwiser](https://github.com/bnnm/wwiser) (`wwiser.py`)
- [bg3-sids.wiki](https://github.com/HumansDoNotWantImmortality/bg3-sids.wiki)

## Configuration

Copy `.env.example` to `.env` and set paths.

```env
WWISER_PY=/absolute/path/to/wwiser.py
VGMSTREAM_DIR=/absolute/path/to/vgmstream/folder
UNPACKED_DATA=/absolute/path/to/UnpackedData
AUDIO_CONVERTED=/absolute/path/to/converted
AUDIO_LABELED=/absolute/path/to/labeled
SIDS_WIKI=/absolute/path/to/bg3-sids.wiki
PROGRESS_BAR_MODE=auto
BG3_LABEL_STRICT=0
BG3_LABEL_REPORT=/absolute/path/to/label-report.json
```

### Environment Variables

- `WWISER_PY`: required only when bank decoding is enabled
- `VGMSTREAM_DIR`: required only when conversion is enabled
- `UNPACKED_DATA`: required when convert/decode/group stages are enabled
- `AUDIO_CONVERTED`: required when convert/group/sort stages are enabled
- `AUDIO_LABELED`: optional output root for labeled assets
- `SIDS_WIKI`: required only when SID sorting is enabled
- `PROGRESS_BAR_MODE`: `auto`, `alive`, or `basic`
- `BG3_LABEL_STRICT`: `1` to fail when known label coverage gaps remain
- `BG3_LABEL_REPORT`: optional JSON report path for consolidated label results

### Pipeline Toggles

- `BG3_CONVERT=1|0`
- `BG3_DECODE_BANKS=1|0`
- `BG3_GROUP_BY_BANK=1|0`
- `BG3_SORT_BY_SID=1|0`

Falsy values are: empty string, `0`, `false`, `no`.

## Usage

Run full pipeline:

```sh
python3 main.py
```

Run only SID labeling (if converted WAVs already exist):

```sh
BG3_CONVERT=0 BG3_DECODE_BANKS=0 BG3_GROUP_BY_BANK=0 BG3_SORT_BY_SID=1 python3 main.py
```

Run label-only audit with explicit report output:

```sh
BG3_CONVERT=0 BG3_DECODE_BANKS=0 BG3_GROUP_BY_BANK=0 BG3_SORT_BY_SID=1 \
BG3_LABEL_REPORT=/tmp/bg3-label-report.json \
python3 main.py
```

Run strict label audit:

```sh
BG3_CONVERT=0 BG3_DECODE_BANKS=0 BG3_GROUP_BY_BANK=0 BG3_SORT_BY_SID=1 \
BG3_LABEL_STRICT=1 \
BG3_LABEL_REPORT=/tmp/bg3-label-report.json \
python3 main.py
```

Run with SID sorting disabled (does not require `SIDS_WIKI`):

```sh
BG3_SORT_BY_SID=0 python3 main.py
```

## Shared Verify Surface

Prefer the repo-local `make` targets when you want the shared tooling contract:

- `make doctor`: confirm `python3`, `vgmstream-cli`, and a valid `WWISER_PY` path are available on this machine.
- `make verify-fast`: run the fast repo-local test surface.
- `make verify`: run the default repo-local verification surface.
- `make verify-security`: run the shared security and policy checks around this repo.
- `make verify-ci`: run the generated CI wrapper over the same local targets.

## Review Flow

From the workspace root, start with:

1. `tpl repo bg3-audio-converter-autolabel-fix`
1. `make repo-brief TOOLING_SUMMARY_ONLY=1`
1. `make verify-fast`
1. `make review-ready TOOLING_SUMMARY_ONLY=1`

Use `REVIEW_READY_SCOPE=full make review-ready TOOLING_SUMMARY_ONLY=1` only
when you need heavier CI-style detail before promotion.

## Direct Auto-Labeler CLI

`auto_labeler.py` can be run independently.

```sh
python3 auto_labeler.py \
  --src /path/to/converted/Shared \
  --dst /path/to/labeled/Shared \
  --wiki /path/to/bg3-sids.wiki \
  --duplicate-mode copy \
  --dry-run \
  --report /tmp/label-report.json
```

### Auto-Labeler Options

- `--duplicate-mode copy|move|link` (default: `copy`)
- `--conflict-mode suffix` (default: `suffix`)
- `--dry-run` to plan without writes
- `--report PATH` to write JSON summary

## Safe Label Operator

The stable label-only profile is `label-fixture-core`. It runs the real
`auto_labeler.py` planning and copy logic without requiring `vgmstream`,
`wwiser`, game installation paths, network access, or provider calls. The
existing `main.py` and direct auto-labeler commands remain available as
compatibility entrypoints for the full/manual pipeline.

From a clean checkout, verify the tracked-fixture profile:

```sh
./scripts/label-doctor --stage smoke
./scripts/label-smoke
```

`label-smoke` exercises the complete bounded path: read-only plan, approved
copy-only apply, generated report inspection, repeat apply with no new copies,
unconfirmed rollback refusal, confirmed rollback, and source hash preservation.
It writes clean/current-SHA evidence to
`artifacts/tooling/bg3-label-core/operator-result.json` and removes its generated
smoke run before returning.

For converted local assets, choose a unique run name and inspect the plan first:

```sh
./scripts/label-doctor \
  --stage plan \
  --src /path/to/converted/Shared \
  --wiki /path/to/bg3-sids.wiki \
  --run-name shared-review-001

./scripts/label-plan \
  --src /path/to/converted/Shared \
  --wiki /path/to/bg3-sids.wiki \
  --run-name shared-review-001
```

Planning is read-only: it does not create the artifact root, output directories,
or a report file. The JSON printed to standard output contains every planned,
missing, or ambiguous task.

Apply only after reviewing that JSON:

```sh
APPROVE=1 ./scripts/label-apply \
  --src /path/to/converted/Shared \
  --wiki /path/to/bg3-sids.wiki \
  --run-name shared-review-001

python3 -m json.tool \
  artifacts/bg3-label/generated/shared-review-001/.bg3-label/report.json
```

The operator only copies into
`artifacts/bg3-label/generated/shared-review-001/labels`. Its ownership marker
and report are stored under that run's `.bg3-label/` directory. It refuses a
dirty worktree, unsafe run names, symlinked operator roots, unknown pre-existing
output, or changed inputs. It never moves or deletes source audio.

Run the same approved command again to verify idempotence. The second report
must show `copied: 0`, all resolved labels as `skipped_existing`, and
`idempotent_repeat: true`. Normal operator runs remain available for inspection;
remove one only with explicit confirmation:

```sh
CONFIRM=1 ./scripts/label-rollback --run-name shared-review-001
```

Rollback validates the ownership marker and every generated file hash. It
refuses modified, untracked, incomplete, or symlinked runs, removes only the
named generated run, and never removes source or wiki content.

## Verification

Run the repo test suite from the repo root:

```sh
make verify-fast
```

Underlying repo-native command:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v
```

For a live audit with real converted assets, point `SIDS_WIKI` at the wiki checkout and run the label-only command above. Use `BG3_LABEL_STRICT=1` only when you want unresolved known mappings to fail the run.

## Notes

- Default duplicate handling is `copy`, preserving all mappings when IDs are reused.
- Labeling output defaults to `AUDIO_CONVERTED/labeled` if `AUDIO_LABELED` is unset.
- Source input directories are validated and no longer auto-created.
- Label reports include labeled, missing, ambiguous, conflict, and unused-source counts for both `Shared` and `SharedDev`.
- Bank-aware matching prefers a source file from the bank named by the wiki file before falling back to a unique global SID match.
- “Known files” means the mappings currently present in `bg3-sids.wiki`; the wiki itself is not a full index of every BG3 audio asset.
