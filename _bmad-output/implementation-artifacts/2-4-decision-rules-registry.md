# Story 2.4: Decision Rules Registry (Sizing/Constraints/Filters)

Status: done

## Story

As a quant researcher,
I want reusable decision rules for sizing and constraints,
so that decision logic is composable and consistent.

## Acceptance Criteria

1. Given a strategy with rule references, when rules are resolved, then only rules from the controlled rule registry are allowed.
2. Given rule outputs are merged, when conflicts occur, then outputs are deterministically mergeable (later overrides earlier).

## Tasks / Subtasks

- [x] Implement rule registry with sizing/constraint/filter resolution
- [x] Add built-in example rules
- [x] Add deterministic merge helper for rule outputs
- [x] Add unit tests for registry and merge behavior

## Dev Notes

- Rules return partial output dicts with stable keys for deterministic merging.
- No inline code execution; rule names are registry references only.

### Project Structure Notes

- Registry under `src/decision_intel/decision/rules/`.
- Tests under `tests/decision_intel/decision/`.

### References

- `_bmad-output/planning-artifacts/epics.md` (Epic 2, Story 2.4)
- `_bmad-output/project-context.md` (rule registry constraint)

## Dev Agent Record

### Agent Model Used

GPT-5 (Codex CLI)

### Debug Log References

### Completion Notes List

- Rule registry implemented with deterministic merge helper and tests passing.

### File List
