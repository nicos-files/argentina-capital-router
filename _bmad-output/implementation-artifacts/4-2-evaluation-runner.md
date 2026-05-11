# Story 4.2: Strategy Evaluation Runner

Status: done

## Story

As a quant researcher,
I want to evaluate a strategy run with a consistent metric set,
so that results are comparable across runs.

## Acceptance Criteria

1. Given decision outputs exist, when evaluation runs, then metrics are computed deterministically.
2. Given metrics are computed, when persisted, then the evaluation artifact is indexed in the manifest.

## Tasks / Subtasks

- [x] Implement evaluation runner from manifest
- [x] Validate manifest contract and artifact index entries
- [x] Add tests for evaluation runner

## Dev Notes

- No cross-horizon normalization or comparisons yet.

### Project Structure Notes

- Runner under `src/decision_intel/evaluation/`.
- Tests under `tests/decision_intel/evaluation/`.

### References

- `_bmad-output/planning-artifacts/epics.md` (Epic 4, Story 4.2)

## Dev Agent Record

### Agent Model Used

GPT-5 (Codex CLI)

### Debug Log References

### Completion Notes List

- Runner implemented with manifest contract compliance and tests passing.

### File List
