---
stepsCompleted: [1, 2, 3, 4, 5, 6, 7, 8]
inputDocuments:
  - _bmad-output/planning-artifacts/prd.md
workflowType: 'architecture'
project_name: 'quant-trading-bot'
user_name: 'Naguilar'
date: '2026-01-09T01:01:47-03:00'
lastStep: 8
status: 'complete'
completedAt: '2026-01-09T09:26:10-03:00'
---

# Architecture Decision Document

_This document builds collaboratively through step-by-step discovery. Sections are appended as we work through each architectural decision together._
## Project Context Analysis

### Requirements Overview

**Functional Requirements:**
The PRD defines 40 FRs across eight categories: strategy/decision abstraction, signal?decision transformation, evaluation/comparability, explainability/traceability, configuration/versioning, run orchestration/replay, reporting/artifacts, and basic portfolio views. Architecturally, this implies a modular decision layer with stable contracts, deterministic rule application, a unified evaluation subsystem, and consistent artifact generation for both machine and human consumption.

**Non-Functional Requirements:**
Deterministic batch execution, reproducibility, auditability, and traceability are non-negotiable. Performance is bounded by batch windows (intra-day 30–90 min; daily 2–4 hrs), with reports generated within 5–15 minutes post-run. Security requires least-privilege RBAC, access logging, and secrets management. Scalability targets 10–50 strategies, 2–4 horizons, 1–6 runs/day without architectural changes.

**Scale & Complexity:**
- Primary domain: backend/data/ML decision pipeline
- Complexity level: high (brownfield integration, multi-horizon strategies, strict auditability)
- Estimated architectural components: 8–12 core components

### Technical Constraints & Dependencies

- Python-only implementation for MVP/Growth; packaged as module within existing repo.
- Brownfield: must reuse existing ETL/feature/training pipelines; integrate via stable interfaces.
- CLI entrypoint for run/evaluate/report/replay workflows; notebook consumption via standardized outputs.
- Deterministic batch runs with versioned configs and data snapshots.
- Reporting is batch/static (CSV/JSON/Markdown/HTML/plots), no real-time UI.

### Cross-Cutting Concerns Identified

- End-to-end reproducibility (config/version/data snapshotting)
- Audit trail and decision provenance
- Deterministic rule evaluation and output consistency
- Access control + access logging for sensitive actions
- Artifact retention and traceable run metadata
- Explainability artifacts bound to decision outputs
## Starter Template Evaluation

### Primary Technology Domain

Backend/data/ML decision pipeline (batch-oriented), integrated into the existing repository.

### Starter Options Considered

- **No starter baseline (selected):** extend the existing repo structure to avoid introducing new scaffolding or external templates.
- **CLI-focused starter** (not selected): would introduce additional conventions and dependencies not needed for MVP.

### Selected Starter: No starter baseline (extend existing repo)

**Rationale for Selection:**
- Brownfield integration is a hard requirement.
- Determinism and reproducibility are prioritized over scaffolding convenience.
- Minimal dependencies reduce risk and keep behavior stable.
- Existing repo conventions should be preserved.

**Initialization Command:**
None (use existing repo structure).

**Architectural Decisions Provided by Starter:**

**Language & Runtime:**
- Python-only for MVP/Growth.

**Configuration:**
- YAML as primary format (human-friendly).
- Optional JSON for machine-generated configs.
- One canonical schema/version.

**Artifact Storage:**
- Filesystem-first, versioned run directories.
- Parquet for large tabular artifacts.
- JSON for metadata/manifests.
- CSV only for small summaries.

**Orchestration:**
- Reuse existing Prefect if already present.
- Otherwise CLI-run batches and schedule via cron/existing scheduler.
- Replayability prioritized over orchestration sophistication.

**Packaging/Workflow:**
- Match existing project conventions.
- Default to `pip + requirements.txt` unless repo already uses Poetry/Conda.

**Reporting:**
- Markdown + HTML reports.
- Matplotlib for simple plots.
- Notebooks optional, consume standardized artifacts.

**Note:** No starter initialization is required; first implementation story should define the decision-layer module structure and CLI entrypoints in the existing repo.
## Core Architectural Decisions

### Decision Priority Analysis

**Critical Decisions (Block Implementation):**
- Decision data contracts and artifact schemas (dataclasses/pydantic + JSON Schema + PyArrow)
- Deterministic batch execution with filesystem-first artifact storage
- Configuration versioning and schema evolution approach
- OS-level access + app-level RBAC checks for sensitive actions
- CLI-only execution surface (no API in MVP)

**Important Decisions (Shape Architecture):**
- Hybrid in-process + file-based interfaces
- Error handling model (exceptions vs. result objects)
- Reporting outputs and formats
- Parallelization strategy across strategies/horizons

**Deferred Decisions (Post-MVP):**
- Centralized logging/monitoring integration
- Containerization
- External API surface

### Data Architecture

- **Data modeling:** dataclasses/pydantic for metadata + PyArrow schemas for Parquet tables (version not verified)
- **Validation:** pydantic for metadata + Arrow schema checks + minimal critical table assertions (version not verified)
- **Schema evolution:** manifest includes schema version; readers remain backward-compatible
- **Caching:** no explicit cache; run artifacts are the cache

### Authentication & Security

- **Authentication:** OS-level access only
- **Authorization/RBAC:** OS-level + lightweight app-level role checks for sensitive actions
- **Security logging:** structured per-run audit logs + artifact access logging
- **Encryption:** rely on storage-level encryption
- **API security:** no API surface in MVP (CLI-only)

### API & Communication Patterns

- **Interface style:** hybrid in-process typed functions + file-based contracts for persistence
- **Contract management:** dataclasses/pydantic + JSON Schema (metadata) + PyArrow schema (tables) (version not verified)
- **Error handling:** exceptions for programmer errors; result objects for expected failures; structured error logs per run
- **Documentation:** internal markdown docs for module interfaces + artifact schemas
- **IPC:** none; all in-process

### Frontend Architecture

Not applicable (CLI-only, batch-oriented).

### Infrastructure & Deployment

- **Hosting/execution:** reuse existing execution environment; no Docker in MVP/Growth
- **CI/CD:** reuse existing CI if present; otherwise minimal lint/test
- **Environment config:** env vars for secrets + YAML for versioned config
- **Monitoring/logging:** file-based + structured per-run JSON/JSONL; no central aggregation
- **Scaling:** partition by strategy/horizon with parallel batch runs

### Decision Impact Analysis

**Implementation Sequence:**
1) Define config schema + artifact schemas + manifest format
2) Implement decision layer interfaces and decision output contracts
3) Build batch CLI entrypoints (run/evaluate/report/replay)
4) Implement evaluation + reporting pipeline
5) Add audit logging and RBAC checks
6) Add parallelization across strategies/horizons

**Cross-Component Dependencies:**
- Schema/versioning decisions affect all modules (config loader, decision engine, evaluator, reporter)
- Artifact layout drives replayability and auditability
- RBAC + logging must wrap run execution and artifact access
## Implementation Patterns & Consistency Rules

### Pattern Categories Defined

**Critical Conflict Points Identified:**
Naming conventions, artifact layout, schema formats, logging structure, and error handling.

### Naming Patterns

**Database Naming Conventions:**
Not applicable (filesystem-first artifacts; no DB in MVP).

**API Naming Conventions:**
Not applicable (CLI-only, no API surface in MVP).

**Code Naming Conventions:**
- Python modules/packages: `snake_case`
- Classes: `PascalCase`
- Functions/variables: `snake_case`
- Constants: `SCREAMING_SNAKE_CASE`

**Config/Metadata Field Naming:**
- Use `snake_case` for YAML/JSON fields and schema properties.

**Artifact Naming:**
- `{run_id}__{ts}__{strategy_id}__{horizon}__{artifact_type}.ext`

### Structure Patterns

**Project Organization:**
- Decision layer root package: `decision_intel/`
- Subpackages: `configs/`, `contracts/`, `decision/`, `evaluation/`, `reporting/`, `replay/`, `cli/`, `utils/`

**File Structure Patterns:**
- Artifacts: `runs/{run_id}/artifacts/`
- Logs: `runs/{run_id}/logs/run.jsonl` and `runs/{run_id}/logs/audit.jsonl`
- Reports: `runs/{run_id}/reports/`
- Manifests/metadata: `runs/{run_id}/manifests/`

**Tests:**
- `tests/` at repo root, mirroring package paths.

### Format Patterns

**Artifact Manifests:**
- JSON with top-level keys: `schema_version`, `run_id`, `strategy_id`, `horizon`, `timestamps`, `inputs`, `outputs`, `metrics`, `artifact_index`

**Date/Time Formats:**
- ISO 8601 UTC strings.

**Error Formats:**
- `{error_code, message, context, run_id}`

### Communication Patterns

**Event System Patterns:**
Not applicable (no event bus in MVP).

**State Management Patterns:**
Not applicable (no frontend).

### Process Patterns

**Validation:**
- Validate configs before run execution.
- Validate artifacts at write-time (schema + minimal critical assertions).

**Error Handling:**
- Expected failures return result objects.
- Programmer errors raise exceptions.
- All errors logged to run logs.

### Enforcement Guidelines

**All AI Agents MUST:**
- Follow naming and file layout conventions exactly.
- Write artifacts only via defined contracts/schemas.
- Log run events and audit events to the specified JSONL files.

**Pattern Enforcement:**
- Document deviations in `runs/{run_id}/manifests/` notes or in PR notes.
- Update this section before introducing new conventions.

### Pattern Examples

**Good Examples:**
- `runs/2026-01-08T233838Z/artifacts/2026-01-08T233838Z__2026-01-08T233900Z__strategy_alpha__daily__decisions.parquet`
- `decision_intel/contracts/decision_output.py`
- `runs/2026-01-08T233838Z/logs/run.jsonl`

**Anti-Patterns:**
- Mixed camelCase/snake_case fields in config/metadata.
- Writing artifacts outside `runs/{run_id}/...`.
- Logging to ad-hoc file paths.
## Project Structure & Boundaries

### Complete Project Directory Structure
```
quant-trading-bot/
- README.md
- requirements.txt
- main.py
- src/
  - run.py
  - data/
  - features/
  - pipeline/
  - orchestrator/
  - backtest/
  - execution/
  - simulations/
  - validators/
  - utils/
  - agents/
  - sanity_check/
  - autogen/
  - decision_intel/
    - __init__.py
    - cli/
      - __init__.py
      - run.py
      - evaluate.py
      - report.py
      - replay.py
    - configs/
      - __init__.py
      - schema.yaml
      - examples/
    - contracts/
      - __init__.py
      - decision_output.py
      - evaluation_output.py
      - manifest_schema.json
      - metadata_models.py
      - table_schemas.py
    - decision/
      - __init__.py
      - rules.py
      - sizing.py
      - constraints.py
      - engine.py
    - evaluation/
      - __init__.py
      - metrics.py
      - comparators.py
      - portfolio.py
    - reporting/
      - __init__.py
      - markdown_report.py
      - html_report.py
      - plots.py
    - replay/
      - __init__.py
      - loader.py
      - reproducer.py
    - utils/
      - __init__.py
      - io.py
      - logging.py
      - time.py
- runs/
  - {run_id}/
    - artifacts/
    - logs/
      - run.jsonl
      - audit.jsonl
    - manifests/
    - reports/
- tests/
  - decision_intel/
  - pipeline/
  - features/
- scripts/
- docs/
- simulations/
- _bmad-output/
```

### Architectural Boundaries

**API Boundaries:**
- None in MVP (CLI-only). Public entrypoints are CLI commands in `src/decision_intel/cli/`.

**Component Boundaries:**
- Existing data/feature/training pipeline remains in `src/data`, `src/features`, `src/pipeline`.
- Decision intelligence layer lives in `src/decision_intel` and consumes signals/model outputs via in-process interfaces plus file-based artifacts.

**Service Boundaries:**
- No networked services in MVP.
- Orchestration boundaries: `src/orchestrator` (if used) triggers decision_intel CLI or in-process APIs.

**Data Boundaries:**
- Raw/feature/model artifacts remain in existing pipeline areas.
- Decision artifacts, evaluation outputs, and reports are stored under `runs/{run_id}/...` with manifest-driven schemas.

### Requirements to Structure Mapping

**Decision Abstraction & Strategy Definition:**
- `src/decision_intel/configs/`
- `src/decision_intel/contracts/`
- `src/decision_intel/decision/`

**Signal ? Decision Transformation:**
- `src/decision_intel/decision/engine.py`
- `src/decision_intel/decision/rules.py`

**Evaluation & Comparability:**
- `src/decision_intel/evaluation/`
- `src/decision_intel/reporting/`

**Explainability & Traceability:**
- `src/decision_intel/reporting/`
- `runs/{run_id}/manifests/`
- `runs/{run_id}/logs/`

**Configuration & Versioning:**
- `src/decision_intel/configs/`
- `src/decision_intel/contracts/manifest_schema.json`

**Run Orchestration & Replay:**
- `src/decision_intel/cli/`
- `src/decision_intel/replay/`
- `src/orchestrator/` (if reused)

**Reporting & Artifacts:**
- `src/decision_intel/reporting/`
- `runs/{run_id}/reports/`
- `runs/{run_id}/artifacts/`

**Portfolio Views (Basic):**
- `src/decision_intel/evaluation/portfolio.py`

### Integration Points

**Internal Communication:**
- In-process typed function interfaces between pipeline outputs and decision_intel.
- File-based artifact contracts under `runs/{run_id}/...`.

**External Integrations:**
- None in MVP.

**Data Flow:**
- Existing pipeline generates model outputs ? decision_intel applies rules and produces decisions ? evaluation computes metrics ? reporting generates Markdown/HTML and plots ? artifacts/logs/manifests stored under run directory.

### File Organization Patterns

**Configuration Files:**
- Decision configs and schema in `src/decision_intel/configs/`.
- Versioned run configs saved under `runs/{run_id}/manifests/`.

**Source Organization:**
- Decision intelligence code isolated in `src/decision_intel/` with subpackages by responsibility.

**Test Organization:**
- `tests/decision_intel/` mirrors `src/decision_intel/`.
- Existing tests remain under current `tests/` structure.

**Asset Organization:**
- Run artifacts and reports live only under `runs/{run_id}/...`.

### Development Workflow Integration

**Development Server Structure:**
- CLI-first: run commands from `src/decision_intel/cli/` or `src/run.py`.

**Build Process Structure:**
- No separate build output; artifacts are run outputs in `runs/`.

**Deployment Structure:**
- Batch execution in existing environment; schedule via existing tools or cron.
## Architecture Validation Results

### Coherence Validation

**Decision Compatibility:**
All decisions are internally consistent: Python-only, CLI-first, filesystem artifacts, and deterministic batch orientation align with the brownfield constraints and reporting requirements. No conflicts between orchestration approach and artifact storage.

**Pattern Consistency:**
Naming, structure, and logging patterns align with the chosen stack and CLI workflows. Artifact schemas and logging conventions are consistent with reproducibility/auditability goals.

**Structure Alignment:**
The `decision_intel/` package boundaries map cleanly to functional requirements, and the `runs/{run_id}/...` structure supports replay, traceability, and reporting.

### Requirements Coverage Validation

**Epic/Feature Coverage:**
No epics provided; FR categories are fully mapped to components in the structure section.

**Functional Requirements Coverage:**
All FR categories (decision abstraction, signal?decision, evaluation, explainability, config/versioning, orchestration/replay, reporting, portfolio views) are explicitly supported by the architecture.

**Non-Functional Requirements Coverage:**
Performance windows are addressed via batch orchestration and parallel strategy/horizon execution. Security and RBAC are addressed via OS-level access + app checks. Auditability and traceability are covered through run manifests, logs, and artifact layout. Scalability is supported through partitioned runs.

### Implementation Readiness Validation

**Decision Completeness:**
Core decisions documented; versions intentionally not verified per instruction.

**Structure Completeness:**
Complete project tree defined with explicit module boundaries and artifact layout.

**Pattern Completeness:**
Naming, schema, logging, validation, and error handling patterns are defined with examples.

### Gap Analysis Results

**Critical Gaps:**
- None identified.

**Important Gaps:**
- None identified.

**Nice-to-Have Gaps:**
- Optional: add a formal config schema document in `docs/` for cross-team reference.

### Validation Issues Addressed

- Version verification intentionally skipped per user direction.

### Architecture Completeness Checklist

- [x] Project context thoroughly analyzed
- [x] Scale and complexity assessed
- [x] Technical constraints identified
- [x] Cross-cutting concerns mapped
- [x] Critical decisions documented (versions not verified)
- [x] Technology stack specified
- [x] Integration patterns defined
- [x] Performance considerations addressed
- [x] Naming conventions established
- [x] Structure patterns defined
- [x] Process patterns documented
- [x] Complete directory structure defined
- [x] Component boundaries established
- [x] Integration points mapped
- [x] Requirements to structure mapping complete

### Architecture Readiness Assessment

**Overall Status:** READY FOR IMPLEMENTATION

**Confidence Level:** High

**Key Strengths:**
- Deterministic, reproducible batch design
- Clear decision/output contracts
- Strong auditability and traceability

**Areas for Future Enhancement:**
- Centralized logging/monitoring integration
- Optional API surface
- Containerization

### Implementation Handoff

**AI Agent Guidelines:**
- Follow architectural decisions and patterns exactly.
- Use defined schemas and artifact layouts.
- Keep runs deterministic and fully traceable.

**First Implementation Priority:**
- Implement config schema + artifact schemas + decision output contracts.
## Architecture Completion Summary

### Workflow Completion

**Architecture Decision Workflow:** COMPLETED
**Total Steps Completed:** 8
**Date Completed:** 2026-01-09T09:26:10-03:00
**Document Location:** _bmad-output/planning-artifacts/architecture.md

### Final Architecture Deliverables

**Complete Architecture Document**
- Architectural decisions documented (versions not verified per instruction)
- Implementation patterns for consistency
- Complete project structure and boundaries
- Requirements-to-structure mapping
- Validation confirming coherence and completeness

**Implementation Ready Foundation**
- Clear decision-layer contracts and artifact schemas
- Deterministic, replayable batch execution model
- Audit-ready run structure with logs and manifests

**AI Agent Implementation Guide**
- Follow documented patterns and file layout
- Use defined schemas and artifact naming
- Keep runs deterministic and fully traceable

### Implementation Handoff

**For AI Agents:**
This architecture document is the implementation guide for quant-trading-bot. Follow all decisions, patterns, and structures exactly as documented.

**First Implementation Priority:**
Define config schema + artifact schemas + decision output contracts, then scaffold the `decision_intel/` package and CLI entrypoints.

**Development Sequence:**
1. Add decision_intel core package structure
2. Implement contracts + config validation
3. Implement decision engine + evaluation pipeline
4. Implement reporting + replay
5. Add audit logging + RBAC checks

### Quality Assurance Checklist

- [x] Architecture coherence validated
- [x] Requirements coverage validated
- [x] Implementation readiness validated
- [x] Patterns and structure documented

---

**Architecture Status:** READY FOR IMPLEMENTATION
**Next Phase:** Begin implementation using the architectural decisions and patterns documented herein.
**Document Maintenance:** Update this architecture when major technical decisions change during implementation.

