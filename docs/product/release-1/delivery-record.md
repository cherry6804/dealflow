# Release 1 Delivery Record: Verified Branch and Tree Hashes

**Status:** verified read-only on 2026-10-30 against `origin/main` and `origin/develop` after PR #130 merged.

## Branch policy
- `main`: original repository baseline plus the approved baseline-aware CI workflow (`.github/workflows/ci.yml`).
- `develop`: all development implementation, E01–E13.
- Future feature branches originate from `develop`.

## Verified heads

| Ref | Commit | Tree | Notes |
|---|---|---|---|
| `origin/main` | `1b370fb` | `390b74beb9cef4a1cebe6f4c3c7e6a69a351035c` | Merge of PR #130. Parents `9efac07`, `05af559`. |
| `origin/develop` | `89fe2cc` | `03627f1b5722702e94be3c6ec93d26ca9f79aa35` | Merge of PR #132 (provider secrets). Parents `3f836b0`, `102bdc7`. Contains E01–E13 and the provider-secrets foundation. |
| `origin/develop` (previous) | `3f836b0` | `9e6c107c3343307690d4b4484c228e48689df47b` | Merge of PR #129. Parents `4772a72`, `9efac07`. Contains E01–E13. |
| `origin/restoration/revert-accidental-e13-merge` | `05af559` | `390b74beb9cef4a1cebe6f4c3c7e6a69a351035c` | Restoration commit `f25ffc9` plus PR #131 (CI fix). |
| `origin/corrective/ci-baseline-aware-validation` | `a9dfea2` | `390b74beb9cef4a1cebe6f4c3c7e6a69a351035c` | CI-only commit on `f25ffc9`. Merged by PR #131. |

## Reference commits

| Commit | Meaning | Tree |
|---|---|---|
| `9dd7d4d` | Original repository baseline | `2f424d99ef200914bcc281961c579c7b3d65c049` |
| `f25ffc9` | Revert of accidental E13 merge `9efac07` (`git revert -m 1`) | `2f424d99ef200914bcc281961c579c7b3d65c049` |
| `9efac07` | Accidental merge of E13 into `main` (PR #128) | `9e6c107c3343307690d4b4484c228e48689df47b` |
| `de42012` | E13 head | `9e6c107c3343307690d4b4484c228e48689df47b` |
| `4772a72` | E12 merge (PR #127), first parent of develop's PR #129 | `d5839c8f051bd4d060224f99ff88921aa3ab89af` |

Tree excluding `.github/workflows/ci.yml` on `main`: `fb5d2bf4e0ae66013b9829b8ef822fa1ae8cf8ba` (the value the baseline-aware CI check matches).

## Verification

- `origin/main` differs from the original baseline `9dd7d4d` only in `.github/workflows/ci.yml` (22 lines added). No `backend/` or `frontend/` paths exist on `main`.
- `origin/develop` contains `de42012`, `4772a72` and `9efac07`. Its diff from `4772a72` is the 49 E13 files (+6893 / −9).
- All four E13 migrations are on `develop`: `f3a7b9c1d2e4`, `g4b8c0d2e5f6`, `h5c9d1e3f6a7`, `i7f2c9d4e1a8`. The E13 ADR (`0029`) and architecture document are present.
- The restoration commits `f25ffc9`, `a9dfea2`, `05af559` and `1b370fb` are not ancestors of `origin/develop`.
- No uncommitted tracked changes in the verifying checkout.

## Recording rule
Hashes are recorded only after they are re-verified. Any later change to `main` or `develop` requires this record to be updated by a separate change.
