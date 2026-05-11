# Code Review Flow

This repo uses the shared governance pack without changing its current branch
topology.

## Protected Branches

- `script-enhancement` is the current integration truth for normal delivery
  work.
- `main` stays as the protected stable fallback.
- Implementation work belongs on scoped `feature/*`, `fix/*`, `docs/*`, or
  `chore/*` branches, not directly on `script-enhancement` or `main`.

## Default Local Review Loop

1. From the workspace root, run `tpl repo bg3-audio-converter-autolabel-fix`.
1. Run `make repo-brief TOOLING_SUMMARY_ONLY=1`.
1. Run `make verify-fast`.
1. Run `make review-ready TOOLING_SUMMARY_ONLY=1`.
1. Use `REVIEW_READY_SCOPE=full make review-ready TOOLING_SUMMARY_ONLY=1` only
   when you need heavier CI-style detail.

## Governance Pack

- Feature PR template: `.github/PULL_REQUEST_TEMPLATE/feature.md`
- Promotion PR template: `.github/PULL_REQUEST_TEMPLATE/promotion.md`
- CODEOWNERS: `.github/CODEOWNERS`
- Shared checklist source: `../../.templates/configs/github/review_checklist.md`

## Human Gate

- Human review is required before merge into `script-enhancement`.
- Human review is required again before promotion into `main`.
- If this repo later adopts `dev`, keep the same human gate on `dev -> main`.
- `@codex` can assist with draft review and CI triage, but it is not the merge
  gate.
