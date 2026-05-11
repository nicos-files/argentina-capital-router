# Story 4.3: Cross-Horizon Normalization

Status: done

## Story

As a portfolio decision maker,
I want normalized metrics across horizons,
so that strategies can be compared fairly.

## Acceptance Criteria

1. Given evaluations for multiple horizons, when comparison is requested, then metrics are normalized using explicit, documented rules.
2. Given normalized metrics are produced, when persisted, then the artifact includes method/params and is indexed in the manifest.

## Tasks / Subtasks

- [x] Define normalization schema and constants
- [x] Implement deterministic mean normalizer
- [x] Add writer and tests

## Dev Notes

- No comparisons or summaries yet (Stories 4.4–4.5).

### Project Structure Notes

- Normalization under `src/decision_intel/normalization/`.
- Tests under `tests/decision_intel/normalization/`.

### References

- `_bmad-output/planning-artifacts/epics.md` (Epic 4, Story 4.3)

## Dev Agent Record

### Agent Model Used

GPT-5 (Codex CLI)

### Debug Log References

### Completion Notes List

- Normalization implemented with deterministic mean and tests passing.

### File List
