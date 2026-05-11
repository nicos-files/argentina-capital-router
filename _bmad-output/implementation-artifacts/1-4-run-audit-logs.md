# Story 1.4: Emit Run & Audit Logs

Status: done

## Story

As an ops/reviewer,
I want structured run and audit logs for each run,
so that sensitive actions are traceable.

## Acceptance Criteria

1. Given a run is executed, when run events occur, then `runs/{run_id}/logs/run.jsonl` records structured events with required fields (ts, level, event, run_id, message, context).
2. Given a run is executed, when config changes or artifact access occurs, then `runs/{run_id}/logs/audit.jsonl` records those events with required fields (timestamp_utc, level, event_type, run_id, message, context).

## Tasks / Subtasks

- [ ] Implement structured logging helpers (AC: 1, 2)
  - [ ] Add logger utilities in `src/decision_intel/utils/logging.py` to emit JSONL events
  - [ ] Enforce required fields for run and audit logs
- [ ] Integrate logging with run lifecycle (AC: 1, 2)
  - [ ] Emit run start/finish events
  - [ ] Emit audit events for config snapshot and artifact access
- [ ] Add logging tests (AC: 1, 2)
  - [ ] Add `tests/decision_intel/utils/test_logging.py` for JSONL schema

## Dev Notes

- Logging must be structured and deterministic; no ad-hoc formats.
- Run and audit logs are separate files under the run directory.
- Web research skipped per user instruction and network restrictions.

### Project Structure Notes

- Logging helpers live in `src/decision_intel/utils/logging.py`.
- Tests under `tests/decision_intel/utils/`.

### References

- `_bmad-output/planning-artifacts/epics.md` (Epic 1, Story 1.4)
- `_bmad-output/planning-artifacts/architecture.md` (Logging requirements)
- `_bmad-output/project-context.md` (Structured logs, run directory rules)

## Dev Agent Record

### Agent Model Used

GPT-5 (Codex CLI)

### Debug Log References

### Completion Notes List
- Structured JSONL logging helpers implemented with required fields and tests passing.

### File List
