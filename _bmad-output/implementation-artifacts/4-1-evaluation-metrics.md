# Story 4.1: Evaluation Metrics Contract

Status: done

## Story

As a quant researcher,
I want a standardized evaluation metrics contract,
so that all strategies are measured consistently.

## Acceptance Criteria

1. Given decision outputs exist, when evaluation runs, then decision-level metrics are computed using a standardized, versioned schema.
2. Given metrics are produced, when persisted, then the artifact is indexed in the manifest.

## Tasks / Subtasks

- [x] Define versioned metrics schema and constants
- [x] Add pure metrics calculator interface
- [x] Implement metrics writer and tests

## Dev Notes

- No evaluation runner yet (Story 4.2).

### Project Structure Notes

- Contracts under `src/decision_intel/contracts/evaluation/`.
- Evaluation helpers under `src/decision_intel/evaluation/`.

### References

- `_bmad-output/planning-artifacts/epics.md` (Epic 4, Story 4.1)

## Dev Agent Record

### Agent Model Used

GPT-5 (Codex CLI)

### Debug Log References

### Completion Notes List

- Metrics contract implemented with tests passing.

### File List
