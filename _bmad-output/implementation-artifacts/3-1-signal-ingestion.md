# Story 3.1: Signal Ingestion Contract

Status: done

## Story

As a quant researcher,
I want a clear contract for model signal inputs,
so that decision runs consume signals consistently.

## Acceptance Criteria

1. Given a decision run starts, when signal inputs are loaded, then they conform to a declared schema independent of model training code.
2. Given signal inputs are loaded, when the artifact is recorded, then the manifest artifact_index includes name, type, path, schema_version, and optional content_hash.

## Tasks / Subtasks

- [x] Define versioned signal input schema with reader_min_version
- [x] Implement pure loader/validator with explicit error_code
- [x] Append signal artifact to manifest index
- [x] Add fixture and tests

## Dev Notes

- Loader is pure and deterministic; no network or filesystem scanning beyond provided path.

### Project Structure Notes

- Contracts under `src/decision_intel/contracts/signals/`.
- Tests under `tests/decision_intel/signals/` and fixtures under `tests/decision_intel/fixtures/`.

### References

- `_bmad-output/planning-artifacts/epics.md` (Epic 3, Story 3.1)
- `_bmad-output/project-context.md` (manifest artifact index)

## Dev Agent Record

### Agent Model Used

GPT-5 (Codex CLI)

### Debug Log References

### Completion Notes List

- Signal contract implemented with reader_min_version and artifact indexing.

### File List
