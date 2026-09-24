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

- Install `tpldeck`, `uvbootstrap`, and the Codex Docker bridge from `${WORKSPACE_ROOT}/.templates/scripts/install-shell-helpers.sh`.
- From a `rune` shell, use `codex-run ...` or `codex-docker ...` for agent or container work in the dedicated rootless `codex` Docker environment.
- Keep plain `docker ...` on `rune` for human Docker work.
- If the helpers are missing, check `${WORKSPACE_ROOT}/.templates/runbooks/docker/ubuntu_24_04_wsl2_dual_rootless_docker_runbook.md`.
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
- Use `${WORKSPACE_ROOT}/.templates/docs/observability/tooling_status.md` for the shared bridge inventory and install status.
- Use `${WORKSPACE_ROOT}/.templates/scripts/README.md` for the shared deterministic entrypoint catalog.
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
- Before creating or moving a top-level directory, inspect the folder map in
  `make repo-brief TOOLING_SUMMARY_ONLY=1` and the rendered
  `repo.folder_organization` contract in `tooling/configs/tooling-targets.json`.
- Do not use task, branch, date, or agent names as permanent root categories.
  Update the shared contract before introducing a durable root.

## When Uncertain

- If a change materially affects the audio pipeline, file layout, or labeling semantics, pause and document the options instead of guessing.
- Default to the smallest pipeline-preserving change when the intended behavior is unclear.

## Repository-Specific Notes

- This repo is an `.env`-driven local BG3 audio pipeline, so path handling and configuration validation matter more than broad framework work.
- Keep `README.md` aligned with the actual runtime and test entrypoints so future agents can operate it without rediscovery.

## Review And Promotion Loop

- From `${WORKSPACE_ROOT}`, start repo work with `tpl repo bg3-audio-converter-autolabel`.
- Then run `make repo-brief TOOLING_SUMMARY_ONLY=1`, `make verify-fast`, and
  `make review-ready TOOLING_SUMMARY_ONLY=1`.
- Use `REVIEW_READY_SCOPE=full make review-ready TOOLING_SUMMARY_ONLY=1` only
  when you need heavier CI-style detail.
- Keep implementation work on scoped `feature/*`, `fix/*`, `docs/*`, or
  `chore/*` branches rather than directly on `script-enhancement` or `main`.
- Human review is required before merge into `script-enhancement` and again
  before promotion into `main`.

<!-- tpl:repo-followthrough:start -->

## Scoped Execution And Completion

Policy version: `repo-completion-v8-2026-09-24`.
Repository-specific security, data, integration, and promotion restrictions
remain authoritative within the task.

- Treat action requests as work to finish, not an acknowledgment of capability;
  honor planning-only requests. Keep accepted outcomes across side questions
  and checkpoints. An intermediate milestone, tests, or a review packet is not
  proof of a requested practical run; require observed acceptance evidence.
- Accepted-plan implementation includes reversible gate repair, preservation,
  and review publication without renewed questions. Native gates still apply.
- For a multi-step task or accepted plan, check the full outcome list before
  voluntary closeout. Use the installed deck's completion/handoff check when
  available; otherwise use the linked policy's manual checklist.
  Continue authorized work behind scoped blockers; investigate unknown inputs
  before asking the user.
- Before promising a live run, identify its exact approvals and their current
  evidence. Prepare the reviewable decision first. A plan does not itself grant
  live-action authority; preserve project security and promotion gates.
- If no authorized useful action remains, report the exact affected outcome,
  missing input or rule, attempted versus proposed alternatives, owner, next
  action, and completion proof. Do not invent approvals or retry uncertain
  mutations. Higher-priority instructions and native rules win over a skill.
- Reuse unchanged evidence. Add or repeat a check only for a native gate,
  changed behavior, or a named uncertainty; do not add generic stopping points.

<!-- tpl:quality-review-v1 -->

- For consequential changes, inspect assumptions and use independent outcome
  evidence plus one bounded false-pass check. Unknown review coverage is not
  success; project profiles are review candidates, not automatic gates.
- Start or resume in the owning project root and reread its effective policy
  after a policy change. Linked Markdown is not automatically loaded by Codex.
  Keep hooks retired; do not delegate unless I explicitly request it in the
  current prompt.

First policy/state route (from the project root):
`../../../.templates/scripts/tpl context-primer --policy-refresh --repo-root .`.
Shared policy reference:
`../../../.templates/docs/observability/task_completion_policy.md`.

<!-- tpl:repo-followthrough:end -->

<!-- tpl:repo-navigation:start -->

## Files And CLI Progress

Before adding or moving a file, start at the project root and read the repo README and inspect its layout.
Check `../../../.templates/catalog/folder_organization.toml` for root purpose, owner, and lifecycle.
If rendered, use `repo.folder_organization` for specific placement; section routes apply only where declared.

For a long-running CLI, consult the rendered `repo.cli_output` profile, when installed.
See `../../../.templates/docs/observability/cli_output_policy.md` for progress behavior. Reuse repo-native progress
when available; keep progress on stderr and final results on stdout.

<!-- tpl:repo-navigation:end -->
