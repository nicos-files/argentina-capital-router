---
project_name: 'quant-trading-bot'
user_name: 'Naguilar'
date: '2026-01-09T16:50:46-03:00'
sections_completed: ['technology_stack', 'language_rules', 'framework_rules', 'testing_rules', 'quality_rules', 'workflow_rules', 'anti_patterns']
existing_patterns_found: 7
status: 'complete'
rule_count: 38
optimized_for_llm: true
---

# Project Context for AI Agents

_This file contains critical rules and patterns that AI agents must follow when implementing code in this project. Focus on unobvious details that agents might otherwise miss._

---
**Purpose:**  
This project implements a deterministic, batch-oriented decision intelligence layer that converts model signals into auditable, explainable, and reproducible portfolio decisions. It does not perform live trading or real-time decisioning.


## Technology Stack & Versions

**Core Data Stack**
- pandas
- numpy
- pyarrow
- duckdb
- pyyaml
- hydra-core (optional; use only if it clearly adds value over simple YAML loading)

**ML/Modeling**
- scikit-learn
- xgboost
- lightgbm
- torch
- shap
- lime
- joblib

**Orchestration**
- prefect (reuse if already present; otherwise optional)

**Reporting**
- matplotlib (default)
- seaborn (optional; not required by architecture)

**Other**
- tqdm

**Notes:**
- Exact library versions are inherited from `requirements.txt`; versions were not verified or changed as part of this architecture workflow.
- Prefer minimal dependencies; do not introduce new libraries unless required by Functional Requirements.
## Critical Implementation Rules

### Language-Specific Rules

- Python only for MVP/Growth; keep new code under `src/decision_intel/`.
- Use `argparse` for CLI entrypoints (no new CLI frameworks unless required).
- Use `dataclasses`/`pydantic` for metadata models; keep models typed and explicit.
- Prefer pure functions for deterministic behavior; avoid hidden state or global mutation in decision logic.
- Use `snake_case` for files, functions, and variables; `PascalCase` for classes.
### Framework-Specific Rules

- No web framework or API layer in MVP; CLI-only execution.
- Prefect is optional: reuse it only if it is already part of the existing orchestration flow.
- Hydra is optional: use only if it adds value over simple YAML loading for the decision_intel layer.

### Testing Rules

- Keep tests under `tests/`, mirroring `src/decision_intel/` paths.
- Prefer deterministic tests (fixed inputs, seeded randomness).
- Use frozen time or injected clocks in time-sensitive tests.
- Add golden artifact tests for key outputs.
- Add schema contract tests tied to manifest definitions.
- No-network rule: mock external APIs and data fetches.
- Include at least one end-to-end replay determinism test.

### Code Quality & Style Rules

- Follow the documented naming and file layout conventions from the architecture.
- Keep decision logic deterministic; no hidden state or side effects.
- No mutable globals or singletons.
- Prefer explicit, typed models for metadata and contracts.
- Keep modules small and single-purpose; no cross-layer imports that bypass contracts.
- decision_intel writes only under `runs/{run_id}/...` and reads pipeline outputs only via declared contracts.
- Strict error discipline: expected failures return result objects with `error_code`; unexpected failures must log once with `run_id` and re-raise.
- Use logging helpers from `decision_intel/utils/logging.py` (when available) to keep structured logs consistent.

### Development Workflow Rules

- Keep dependencies minimal; do not add new libraries unless required by Functional Requirements.
- Use `requirements.txt` as the single source of truth for dependencies.
- Prefer changes that preserve the existing repo structure and brownfield constraints.
- Any new CLI entrypoints must live under `src/decision_intel/cli/` and be wired into the existing run flow.
- Implement in small increments in dependency order: contracts -> engine -> evaluation -> reporting -> replay.
- Avoid refactors of existing pipeline modules unless required by Functional Requirements.
- Enforce run directory invariants: every run creates `runs/{run_id}/` with `manifests/`, `logs/`, and `artifacts/` populated.

### Critical Don't-Miss Rules

- No mutable globals/singletons in decision_intel.
- No hidden state between runs; all inputs and outputs must be explicit artifacts.
- Never write outside `runs/{run_id}/...` from decision_intel.
- No network calls in tests; all external APIs must be mocked.
- Keep CLI runs deterministic: fixed inputs, config snapshot, and schema-validated outputs.
- Never bypass contracts when reading pipeline outputs.
- No silent success: skips/degradations must be recorded in the manifest with status and reason.
- Replay is sacred: any breaking change to schemas/contracts must include backward-compatible readers or a migration path.

### Explicitly Out of Scope

- Live trading or broker execution
- Real-time or streaming pipelines
- Web APIs, services, or dashboards
- Automatic model retraining loops
- Multi-tenant or SaaS concerns

## Usage Guidelines

**For AI Agents:**
- Read this file before implementing any code.
- Follow ALL rules exactly as documented.
- When in doubt, prefer the more restrictive option.
- Update this file if new patterns emerge.

**For Humans:**
- Keep this file lean and focused on agent needs.
- Update when technology stack changes.
- Review quarterly for outdated rules.
- Remove rules that become obvious over time.

Last Updated: 2026-01-09T16:50:46-03:00

