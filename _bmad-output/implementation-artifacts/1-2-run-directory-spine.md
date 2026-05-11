# Story 1.2: Create Run Directory Spine

Status: done

## Story

As an ops/research user,
I want each run to create the standard run directory layout,
so that artifacts, logs, and manifests are consistently stored.

## Acceptance Criteria

1. Given a run is initiated, when the run directory is created, then `runs/{run_id}/` exists with `manifests/`, `logs/`, `artifacts/`, and `reports/`.
2. Given a run directory exists, when outputs are written, then the directory is validated before any output is created.

## Tasks / Subtasks

- [ ] Implement run directory initializer (AC: 1, 2)
  - [ ] Add `decision_intel/utils/io.py` helper to create `runs/{run_id}/` with required subfolders
  - [ ] Add validation routine to assert required paths exist before writes
- [ ] Wire validation into run startup (AC: 2)
  - [ ] Ensure run startup calls directory validation before any artifact/log writes
- [ ] Add tests for directory creation/validation (AC: 1, 2)
  - [ ] Add `tests/decision_intel/utils/test_run_dir.py`

## Dev Notes

- Directory layout must match architecture: `runs/{run_id}/manifests`, `logs`, `artifacts`, `reports`.
- Do not introduce outputs outside `runs/{run_id}/...`.
- Web research skipped per user instruction and network restrictions.

### Project Structure Notes

- Utilities belong in `src/decision_intel/utils/`.
- Tests under `tests/decision_intel/utils/`.

### References

- `_bmad-output/planning-artifacts/epics.md` (Epic 1, Story 1.2)
- `_bmad-output/planning-artifacts/architecture.md` (Run directory invariants)
- `_bmad-output/project-context.md` (Run directory rules)

## Dev Agent Record

### Agent Model Used

GPT-5 (Codex CLI)

### Debug Log References

### Completion Notes List
- Run directory spine helpers added with idempotent creation and write-path validation.
- Unittest discovery passes for utils tests.

### File List
