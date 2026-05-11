# Story 1.3: Snapshot Config & Data Identifiers

Status: done

## Story

As a researcher,
I want config snapshots and data snapshot identifiers stored per run,
so that runs are reproducible and comparable.

## Acceptance Criteria

1. Given a run executes, when configuration and data inputs are resolved, then a versioned config snapshot is stored as JSON under `runs/{run_id}/manifests/` and matches the manifest schema config.snapshot_path expectation.
2. Given configuration and data inputs are resolved, when data snapshot identifiers are missing, then the run fails with an explicit error_code and manifest status/reason recorded.

## Tasks / Subtasks

- [ ] Implement config snapshot writer (AC: 1)
  - [ ] Store the resolved config as a versioned JSON file under `runs/{run_id}/manifests/`
  - [ ] Reference the snapshot path in the manifest
- [ ] Enforce data snapshot identifiers (AC: 2)
  - [ ] Add validation that required data snapshot IDs are present before proceeding
  - [ ] Record failure status and error_code in the manifest on missing IDs
- [ ] Add tests for snapshot and validation (AC: 1, 2)
  - [ ] Add `tests/decision_intel/manifests/test_config_snapshot.py`

## Dev Notes

- Snapshots should be deterministic and tied to the manifest schema from Story 1.1.
- Failure must be explicit and recorded in manifest (no silent success).
- Web research skipped per user instruction and network restrictions.

### Project Structure Notes

- Manifest write logic under `src/decision_intel/contracts/` or `src/decision_intel/utils/` as appropriate.
- Tests under `tests/decision_intel/`.

### References

- `_bmad-output/planning-artifacts/epics.md` (Epic 1, Story 1.3)
- `_bmad-output/planning-artifacts/architecture.md` (Manifest spine, determinism)
- `_bmad-output/project-context.md` (No silent success, replay is sacred)

## Dev Agent Record

### Agent Model Used

GPT-5 (Codex CLI)

### Debug Log References

### Completion Notes List
- Config snapshot writer and data snapshot enforcement implemented with tests passing.

### File List
