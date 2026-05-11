# Story 2.2: Implement Strategy Definition Loader

Status: done

## Story

As a quant researcher,
I want to load strategy definitions from versioned config files,
so that I can create variants without changing pipeline code.

## Acceptance Criteria

1. Given a strategy config file exists, when it is loaded, then the system parses it into a typed strategy object deterministically.
2. Given a config fails validation, when loaded, then it fails fast with explicit error_code and human message.

## Tasks / Subtasks

- [x] Implement a deterministic loader for strategy config JSON
- [x] Return typed StrategyDefinition dataclass
- [x] Add schema-aligned validation and loader tests

## Dev Notes

- Loader is pure: no network, no global state, no filesystem scanning beyond provided path.
- No new dependencies.

### Project Structure Notes

- Loader lives under `src/decision_intel/contracts/strategies/`.
- Tests under `tests/decision_intel/contracts/` and fixtures under `tests/decision_intel/fixtures/`.

### References

- `_bmad-output/planning-artifacts/epics.md` (Epic 2, Story 2.2)
- `_bmad-output/project-context.md` (minimal deps, schema versioning)

## Dev Agent Record

### Agent Model Used

GPT-5 (Codex CLI)

### Debug Log References

### Completion Notes List

- Loader implemented with deterministic validation and tests passing.

### File List
