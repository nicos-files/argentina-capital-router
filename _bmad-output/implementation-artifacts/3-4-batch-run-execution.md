# Story 3.4: Batch Run Execution (Decision Only)

Status: done

## Story

As an ops/research user,
I want to execute a batch run for a strategy and config,
so that runs can be scheduled and repeated.

## Acceptance Criteria

1. Given a valid strategy config and run parameters, when a batch decision run is executed, then it produces decision outputs and manifest updates only.
2. Given a run completes, when artifacts are written, then manifest artifact_index includes signals and decisions with schema_version and content_hash.

## Tasks / Subtasks

- [x] Add CLI entrypoint to run decision-only pipeline
- [x] Persist manifest with status transitions
- [x] Add end-to-end CLI test

## Dev Notes

- No evaluation/reporting/replay logic.

### Project Structure Notes

- CLI entrypoint under `src/decision_intel/cli/`.
- Tests under `tests/decision_intel/cli/`.

### References

- `_bmad-output/planning-artifacts/epics.md` (Epic 3, Story 3.4)

## Dev Agent Record

### Agent Model Used

GPT-5 (Codex CLI)

### Debug Log References

### Completion Notes List

- Manifest spine aligned with CLI and E2E test passing.

### File List
