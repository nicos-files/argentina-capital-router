# Story 1.1: Define Run Manifest Schema & Metadata Model

Status: done

## Story

As a researcher,
I want a versioned run manifest schema and metadata model,
so that every run has a consistent, auditable record.

## Acceptance Criteria

1. Given a new run is started, when the manifest is created, then it is the authoritative record of run metadata (schema_version, run_id, timestamps, config snapshot path, data snapshot IDs, authoritative artifact_index, status, skips[]).
2. Given the manifest schema exists, when it is versioned, then it supports backward-compatible readers.
3. Given manifest content is generated, when it is validated, then it conforms to the schema and the schema version is recorded.
4. Given a run progresses, when status is updated, then it uses the standardized RunStatus enum values (CREATED, RUNNING, SUCCESS, FAILED, PARTIAL, SKIPPED).

## Tasks / Subtasks

- [ ] Define manifest schema and versioning (AC: 1, 2, 3)
  - [ ] Create `src/decision_intel/contracts/manifests/run_manifest.schema.json` with required fields, artifact_index, skips[], and versioning
  - [ ] Add schema_version constant and RunStatus enum (CREATED, RUNNING, SUCCESS, FAILED, PARTIAL, SKIPPED) in `src/decision_intel/contracts/metadata_models.py`
- [ ] Implement metadata model (AC: 1, 3)
  - [ ] Add typed manifest model using dataclasses only (no new deps) in `src/decision_intel/contracts/metadata_models.py`
  - [ ] Ensure model captures config refs, data snapshot IDs, input/output artifact index, and status
- [ ] Add schema contract tests (AC: 3)
  - [ ] Add `tests/decision_intel/contracts/test_manifest_schema.py` to validate required fields and versioning

## Dev Notes

- Manifest is the authoritative run record; record status and reason for skips/degradations.
- Functional determinism required; bit-for-bit not required.
- Web research skipped per user instruction and network restrictions.

### Project Structure Notes

- New files live under `src/decision_intel/contracts/` and `tests/decision_intel/contracts/`.
- Do not write outside `runs/{run_id}/...` in later stories.

### References

- `_bmad-output/planning-artifacts/epics.md` (Epic 1, Story 1.1)
- `_bmad-output/planning-artifacts/architecture.md` (Run manifest spine, artifact layout)
- `_bmad-output/project-context.md` (Critical rules: manifest authority, determinism, schema versioning)

## Dev Agent Record

### Agent Model Used

GPT-5 (Codex CLI)

### Debug Log References

### Completion Notes List
- Manifest schema and dataclass model aligned to spine (artifact_index + skips[]).
- Unittest discovery configured via test package init files.

### File List
