# Story 2.3: Support Strategy Variants & Metadata

Status: done

## Story

As a quant researcher,
I want to define strategy variants with explicit metadata,
so that I can compare them under the same decision pipeline.

## Acceptance Criteria

1. Given a base strategy definition, when a variant is defined, then a stable variant identity (strategy_id + variant_id) is required.
2. Given variant metadata is provided, when it indicates a parent (variant_of), then variant_id must be present.

## Tasks / Subtasks

- [x] Add StrategyIdentity helper and key derivation
- [x] Enforce variant_id when metadata.variant_of is set
- [x] Add tests for variant identity handling

## Dev Notes

- Metadata is preserved on StrategyDefinition; identity helpers remain pure and deterministic.

### Project Structure Notes

- Helpers live under `src/decision_intel/contracts/strategies/`.
- Tests under `tests/decision_intel/contracts/`.

### References

- `_bmad-output/planning-artifacts/epics.md` (Epic 2, Story 2.3)
- `_bmad-output/project-context.md` (explicit variant identity)

## Dev Agent Record

### Agent Model Used

GPT-5 (Codex CLI)

### Debug Log References

### Completion Notes List

- Variant identity helper and guardrails implemented with tests passing.

### File List
