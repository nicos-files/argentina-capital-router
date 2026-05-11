# Story 2.1: Define Strategy Config Schema

Status: done

## Story

As a quant researcher,
I want a strategy config schema that captures assumptions, horizons, and decision rules,
so that strategies are defined consistently and are reusable.

## Acceptance Criteria

1. Given a new strategy config is created, when it is validated, then required fields for assumptions, horizon, and rules are enforced.
2. Given the schema exists, when it is versioned, then the decision_intel layer owns the canonical schema version.

## Tasks / Subtasks

- [x] Define strategy config schema with horizon enum and rule references
- [x] Enforce rule registry references (no inline code) via name patterns
- [x] Add schema tests for required fields and rule structure

## Dev Notes

- variant_id is optional; strategy_id is required and stable.
- horizon_params is optional for future tuning without schema changes.
- rules are references only (sizing_rule, constraints, filters).

### Project Structure Notes

- Schema lives in `src/decision_intel/contracts/strategies/strategy_config.schema.json`.
- Tests under `tests/decision_intel/contracts/`.

### References

- `_bmad-output/planning-artifacts/epics.md` (Epic 2, Story 2.1)
- `_bmad-output/planning-artifacts/architecture.md` (config/versioning)
- `_bmad-output/project-context.md` (minimal deps, schema versioning)

## Dev Agent Record

### Agent Model Used

GPT-5 (Codex CLI)

### Debug Log References

### Completion Notes List

- Schema refined for horizon enums and rule references with patterns.
- Unittest discovery passes.

### File List

