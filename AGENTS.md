# AGENTS.md

Root policy for the BG3 audio conversion and auto-labeling workspace.

Profile: local

## Repo-Local Precedence

- Use this file as the root workflow policy for the repository.
- Follow stronger repo-local docs when they exist for a specific surface.
- If `CONTRIBUTING.md` is added later and conflicts with this file, follow `CONTRIBUTING.md`.
- Keep detailed operator steps in `README.md`; keep this file as the stable index.

## Read First / Source of Truth

- `README.md`
- `pyproject.toml`

## Shared Docker Guidance

- Install `tpldeck`, `uvbootstrap`, and the Codex Docker bridge from `/home/rune/code/.templates/scripts/install-shell-helpers.sh`.
- From a `rune` shell, use `codex-run ...` or `codex-docker ...` for agent or container work in the dedicated rootless `codex` Docker environment.
- Keep plain `docker ...` on `rune` for human Docker work.
- If the helpers are missing, check `/home/rune/code/.templates/runbooks/docker/ubuntu_24_04_wsl2_dual_rootless_docker_runbook.md`.
- Do not rely on `/var/run/docker.sock`, the `docker` group, or cross-user socket sharing for Codex work.

## Deterministic Tooling First

- Prefer repo-local deterministic entrypoints over raw bridge commands or prompt-only exploration.
- Prefer the rendered repo-local targets first:
  - `make doctor`
  - `make verify-fast`
  - `make verify`
  - `make verify-security`
  - `make verify-ci`
- Underlying repo-native commands remain:
  - `python3 main.py`
  - `python3 -m unittest -v`
- `make doctor` is the readiness surface for `python3`, `vgmstream-cli`, and a valid `WWISER_PY` path.
- Use `/home/rune/code/.templates/docs/observability/tooling_status.md` for the shared bridge inventory and install status.
- Use `/home/rune/code/.templates/scripts/README.md` for the shared deterministic entrypoint catalog.
- Use `codex-run`, `codex-docker`, `codex-exec`, and `codex-<tool>` only as fallback or when validating the shared bridge layer itself.

## Operating Rules

- Stay within the repo's existing pipeline and naming conventions.
- Prefer small, reviewable changes over broad refactors.
- Treat local media files, metadata, and env-driven paths as untrusted until validated.
- Do not add telemetry, remote services, or paid dependencies unless explicitly requested.
- Choose the most conservative implementation when requirements are ambiguous and document the assumption.

## Workflow Expectations

- Keep diffs tight and avoid unrelated formatting churn.
- Update `README.md` when commands, env setup, or pipeline behavior changes.
- Update or add tests when behavior changes.
- Prefer the repo's documented entrypoints over ad hoc shell chains:
  - `make doctor`
  - `make verify-fast`
  - `make verify`
  - `make verify-security`
  - `make verify-ci`
  - `python3 main.py`
  - `python3 -m unittest -v`
- Do not mark work complete while the relevant verification path is failing.

## Secure Coding Baseline

- Validate `.env`-driven configuration before using it in filesystem or subprocess operations.
- Treat source audio, generated metadata, and labels as untrusted input until checked.
- Avoid unsafe execution or deserialization patterns.
- Guard against path traversal and accidental writes outside the intended working directories.
- Never commit secrets, tokens, or personal credentials.
- Never log secrets or private source material unnecessarily.
- Provide `.env.example` with placeholders if setup docs need env examples.

## Dependency And Testing Policy

- Use the repo's existing Python workflow and dependency tooling.
- Keep dependency additions minimal and justified.
- Prefer deterministic unit or integration checks over one-off manual validation when behavior becomes repeatable.
- Add regression tests for bug fixes where practical.
- Keep tests isolated from network and external services unless the repo already depends on them.

## Docs And Git Hygiene

- Use descriptive branch names and commit messages.
- If behavior changes, document what changed, why it changed, and how to verify it.
- Prefer concise Markdown docs and ISO 8601 dates (`YYYY-MM-DD`) when dates matter.

## When Uncertain

- If a change materially affects the audio pipeline, file layout, or labeling semantics, pause and document the options instead of guessing.
- Default to the smallest pipeline-preserving change when the intended behavior is unclear.

## Repository-Specific Notes

- This repo is an `.env`-driven local BG3 audio pipeline, so path handling and configuration validation matter more than broad framework work.
- Keep `README.md` aligned with the actual runtime and test entrypoints so future agents can operate it without rediscovery.

## Review And Promotion Loop

- From `/home/rune/code`, start repo work with `tpl repo bg3-audio-converter-autolabel-fix`.
- Then run `make repo-brief TOOLING_SUMMARY_ONLY=1`, `make verify-fast`, and
  `make review-ready TOOLING_SUMMARY_ONLY=1`.
- Use `REVIEW_READY_SCOPE=full make review-ready TOOLING_SUMMARY_ONLY=1` only
  when you need heavier CI-style detail.
- Keep implementation work on scoped `feature/*`, `fix/*`, `docs/*`, or
  `chore/*` branches rather than directly on `script-enhancement` or `main`.
- Human review is required before merge into `script-enhancement` and again
  before promotion into `main`.
