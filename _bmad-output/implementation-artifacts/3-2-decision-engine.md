# Story 3.2: Pure Decision Engine Execution

Status: done

## Story

As a quant researcher,
I want signals transformed into positions and sizing deterministically,
so that outputs are reproducible.

## Acceptance Criteria

1. Given validated signals and strategy definitions, when the decision engine runs, then it is pure and deterministic for fixed inputs/configs.
2. Given the engine produces outputs, when rerun with the same inputs, then results are identical.

## Tasks / Subtasks

- [x] Implement pure decision engine (no side effects)
- [x] Add deterministic test

## Dev Notes

- No batch runner or evaluation logic.

### Project Structure Notes

- Engine lives under `src/decision_intel/decision/`.
- Tests under `tests/decision_intel/decision/`.

### References

- `_bmad-output/planning-artifacts/epics.md` (Epic 3, Story 3.2)

## Dev Agent Record

### Agent Model Used

GPT-5 (Codex CLI)

### Debug Log References

### Completion Notes List

- Pure decision engine implemented with tests passing.

### File List
