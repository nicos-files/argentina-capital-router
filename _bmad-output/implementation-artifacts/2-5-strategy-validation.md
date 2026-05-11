# Story 2.5: Strategy Definition Validation

Status: done

## Story

As a quant researcher,
I want strategy definitions validated for completeness before evaluation,
so that invalid strategies fail fast and are traceable.

## Acceptance Criteria

1. Given a strategy config is provided, when validation runs, then invalid schema_version or missing required fields fails fast with explicit error_code.
2. Given a valid config, when validation runs, then it returns the parsed config for downstream use.

## Tasks / Subtasks

- [x] Add validation function reusing loader rules
- [x] Add validation tests for version mismatch and success

## Dev Notes

- Validation is pure and deterministic; no filesystem scanning beyond provided path.

### Project Structure Notes

- Validation lives under `src/decision_intel/contracts/strategies/`.
- Tests under `tests/decision_intel/contracts/`.

### References

- `_bmad-output/planning-artifacts/epics.md` (Epic 2, Story 2.5)
- `_bmad-output/project-context.md` (fail fast, explicit error_code)

## Dev Agent Record

### Agent Model Used

GPT-5 (Codex CLI)

### Debug Log References

### Completion Notes List

- Validation helper implemented with tests passing.
- Epic 2 complete (Stories 2.1–2.5).

### File List
