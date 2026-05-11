# Story 1.5: Determinism Guardrails

Status: done

## Story

As a researcher,
I want deterministic run guardrails enforced,
so that outputs are functionally identical across reruns.

## Acceptance Criteria

1. Given a run starts, when non-deterministic inputs or mutable configs are detected, then the run records status and reason in the manifest and fails with an explicit error_code.
2. Given the same inputs/configs, when a rerun is executed, then decision outputs are functionally identical (bit-for-bit not required).

## Tasks / Subtasks

- [ ] Implement determinism checks (AC: 1)
  - [ ] Validate config snapshot immutability for the run
  - [ ] Validate required data snapshot IDs are present and stable
- [ ] Enforce deterministic rerun checks (AC: 2)
  - [ ] Add optional comparison helper to compare decisions/metrics for functional equivalence
- [ ] Add tests for determinism guardrails (AC: 1, 2)
  - [ ] Add `tests/decision_intel/guards/test_determinism.py`

## Dev Notes

- Failure must be explicit with error_code and manifest status update.
- This story should not introduce evaluation/reporting logic.
- Web research skipped per user instruction and network restrictions.

### Project Structure Notes

- Guardrails can live under `src/decision_intel/utils/` or a new `src/decision_intel/guards/` module if needed.
- Tests under `tests/decision_intel/`.

### References

- `_bmad-output/planning-artifacts/epics.md` (Epic 1, Story 1.5)
- `_bmad-output/planning-artifacts/architecture.md` (Determinism requirements)
- `_bmad-output/project-context.md` (No silent success, replay is sacred)

## Dev Agent Record

### Agent Model Used

GPT-5 (Codex CLI)

### Debug Log References

### Completion Notes List
- Determinism guardrails implemented with fast-fail and skips[] updates.
- Optional functional decision output comparison helper added (opt-in).

### File List
