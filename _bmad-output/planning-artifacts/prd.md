---
stepsCompleted: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
inputDocuments:
  - docs/architecture.md
  - docs/architecture-patterns.md
  - docs/component-inventory.md
  - docs/comprehensive-analysis-main.md
  - docs/contribution-guidelines.md
  - docs/data-models.md
  - docs/data-models-main.md
  - docs/deployment-configuration.md
  - docs/development-guide.md
  - docs/development-instructions.md
  - docs/existing-documentation-inventory.md
  - docs/final-summary.md
  - docs/index.md
  - docs/project-overview.md
  - docs/project-parts-metadata.json
  - docs/project-scan-report.json
  - docs/project-structure.md
  - docs/source-tree-analysis.md
  - docs/technology-stack.md
  - docs/user-provided-context.md
documentCounts:
  briefCount: 0
  researchCount: 0
  brainstormingCount: 0
  projectDocsCount: 20
workflowType: 'prd'
lastStep: 0
---
# Product Requirements Document - quant-trading-bot

**Author:** Naguilar
**Date:** 2026-01-08T23:38:38-03:00

## Executive Summary

You’re evolving an existing batch ML trading pipeline into a **decision intelligence layer** that explicitly connects signals to portfolio actions and evaluation. The goal is to support multi-horizon strategy evaluation, enforce consistent signal ? decision ? evaluation flow, and make decision logic, risk assumptions, and outcomes explainable and reproducible. This work is explicitly **brownfield**: it reuses the current ETL, feature, and training pipelines, and introduces clear interfaces instead of rewriting core modules.

### What Makes This Special

The system stops being a collection of model outputs and becomes a coherent decision framework. It makes explicit **why** a position was taken, how it fits into portfolio logic, how it behaves across regimes, and how assumptions affect outcomes. This elevates evaluation from model accuracy to **decision quality** and **portfolio impact**, enabling systematic iteration across strategies and horizons.

## Project Classification

**Technical Type:** developer_tool (internal decision intelligence layer for a data/ML pipeline)  
**Domain:** fintech (trading/investment)  
**Complexity:** high  
**Project Context:** Brownfield – extending existing system

This PRD defines the missing layer between model signals and portfolio decisions, standardizes evaluation and comparability, and makes strategy behavior interpretable and reproducible across market regimes.

## Success Criteria

### User Success

Users can:
- Understand **why** positions were taken or avoided.
- Trust decisions are consistent with stated assumptions.
- Iterate confidently without second-guessing the system.

**Aha moment:** two strategies with similar model performance behave very differently once mapped to portfolio decisions, and the system makes those differences explicit.

**Outcome:** a small set of decision-ready strategies with explicit assumptions, risk profiles, horizon alignment, and clear guidance on when to use them.

### Business Success

**3-month success:**
- The system is the primary way to evaluate and compare strategies.
- Multiple strategies are run through the same decision/evaluation framework.
- Clear visibility into why strategies are promoted, modified, or discarded.
- Reduced reliance on ad-hoc analysis and notebooks.

**12-month success:**
- Stable decision-ready strategies across long-term and shorter-term horizons.
- Consistent reuse of decision and evaluation abstractions.
- Historical evaluations across regimes inform portfolio choices.
- Improvements are incremental and intentional, not reactive.

**Business metrics:**
- Strategy iteration speed (idea/config change ? evaluated decision)
- Portfolio confidence (clarity/consistency of decisions)
- Reuse of decision logic and evaluation framework

### Technical Success

- Decision logic implemented as explicit, testable components.
- All evaluations run through a single consistent signal ? decision ? evaluation pipeline.
- Standardized, machine-readable outputs for comparison.

**Non-negotiable requirements:**
- Full reproducibility with same inputs and configs.
- Versioned configs for data, features, models, decision rules.
- Deterministic batch runs (no hidden state).
- Decision-level auditability (data snapshot, model version, parameters).

**Performance constraints:**
- Batch runs can take minutes to hours.
- Report generation within a reasonable batch window.
- Scheduled batch execution (daily/intraday) supported.
- Correctness and reproducibility prioritized over speed.

### Measurable Outcomes

- **Strategy iteration cycle time** (idea ? evaluated decision)
- **Decision reproducibility rate** (% of reruns identical)
- **Decision explainability coverage** (% of decisions with linked explanations)
- **Strategy discard efficiency** (# rejected early due to decision behavior)
- **Cross-regime consistency score** (stability across regimes/time)

**Decision confidence is measured by:** reproducibility, explainability completeness, and sensitivity consistency.
**Iteration speed is measured by:** wall-clock time and workflow steps from config change to evaluated output.

## Product Scope

### MVP - Minimum Viable Product

- Explicit decision abstraction layer consuming model signals
- Standardized decision outputs (positions, sizing, assumptions)
- Unified evaluation + reporting pipeline
- Reproducible batch execution with versioned configs
- Basic explainability attached to decisions

### Growth Features (Post-MVP)

- Multi-horizon and multi-strategy support
- Portfolio-level aggregation and comparison
- Regime-aware evaluation and diagnostics
- Improved reporting and visualization
- Sensitivity analysis and scenario testing

### Vision (Future)

A coherent decision research environment where:
- Strategies are composable and assumptions explicit
- Portfolio behavior is continuously understood across regimes
- Institutional memory accumulates what works, when, and why
- Decision intelligence guides capital allocation intentionally (still batch-oriented and explainable)

## User Journeys

**Journey 1: Alex Rivera — Turning Performance Drift into Structured Iteration (Primary User, Success Path)**  
Alex is a quant researcher managing a strategy that recently underperformed relative to expectations. Instead of jumping into ad-hoc notebooks, Alex opens the decision intelligence layer and selects the strategy’s latest run. The system immediately shows how the model’s signals were translated into portfolio decisions, the assumptions applied, and how the strategy behaved across recent regimes.

Alex launches a structured evaluation: the same strategy is rerun with a revised decision rule and a new feature set variant. The system outputs standardized decision artifacts, comparable metrics, and explanations side by side. The “aha” moment arrives when the system highlights that the model was stable, but the decision layer’s risk constraints amplified drawdowns in a volatile regime. Alex updates the decision logic, reruns the evaluation, and promotes the improved version with confidence—without rewriting the pipeline.

**Journey 2: Alex Rivera — The Strategy That Wins on Signals but Loses in Reality (Primary User, Edge Case)**  
Alex tests a new strategy variant that looks strong in isolation—high signal accuracy and impressive backtest metrics. But when mapped into portfolio decisions, it degrades: position sizing and regime constraints expose unstable behavior. The system flags inconsistency across regimes and shows reproducibility drift across runs tied to implicit assumptions.

Instead of debating intuition, Alex inspects the decision trail: input snapshots, model version, and decision parameters. The system makes the hidden assumptions explicit and shows sensitivity to small parameter changes. Alex confidently rejects the strategy early, saving time and avoiding overfitting, and records the reasons for future reference.

**Journey 3: Priya Shah — Allocating Capital Across Horizons (Portfolio Decision Maker)**  
Priya manages capital across long-term and intraday horizons. She compares several decision-ready strategies in a single view: each with standardized outputs, risk profiles, and regime behavior. Two strategies have similar headline returns, but their portfolio impacts diverge once correlation and drawdowns are considered.

The critical moment is allocation: Priya decides to reduce exposure to a short-term strategy and increase allocation to a longer-term one, not because of model metrics, but because decision logic aligns better with portfolio constraints. She documents the rationale using the system’s explainability artifacts and moves forward with confidence.

**Journey 4: Morgan Lee — Keeping the System Running (Admin/Ops)**  
Morgan ensures daily and intraday batches run reliably. They review a schedule dashboard, confirm configuration versions, and run a deterministic batch. When an anomaly appears in outputs, Morgan traces the run to its config hash and input snapshot, reproduces the run, and confirms it was a data drift issue—not a system failure. The pipeline remains stable without ad-hoc fixes.

**Journey 5: Daniela Ortiz — Auditing Decisions After the Fact (Analyst/Reviewer)**  
Daniela is asked to audit why a strategy was promoted last quarter. She pulls the historical run and sees the exact data snapshot, model version, decision rules, and explanation artifacts. The system provides a regime-aware report showing why the strategy was favored at the time, and what would have changed under different assumptions. Daniela validates the decision, reinforcing trust in the process.

### Journey Requirements Summary

These journeys reveal the need for:
- A consistent decision abstraction layer on top of model signals
- Standardized decision outputs and explainability artifacts
- Regime-aware evaluation and comparability across runs
- Deterministic, versioned batch execution with traceability
- Portfolio-level views for allocation decisions
- Audit and replay capabilities for historical decisions
- Operational controls for scheduling and monitoring

## Domain-Specific Requirements

### Fintech Compliance & Regulatory Overview

This is an **internal research and decision-support system** (no live execution, no custody, no client funds, no third-party advice).  
Primary jurisdiction: **US**. Secondary: **EU**.  
Therefore, **SEC/FINRA/MiFID execution or reporting requirements do not apply**.  
Compliance focus is on internal controls, traceability, and data handling.

### Key Domain Concerns

- **Regional compliance:** US primary, EU secondary; no LATAM requirements currently.
- **Security standards:** internal best practices; no SOC2/ISO certification required.
- **Audit requirements:** decision-level auditability is required.
- **Fraud prevention:** internal misuse risks (not adversarial).
- **Data protection:** integrity, access control, and retention for auditability.

### Compliance Requirements

- Maintain internal controls and traceability sufficient for internal review.
- Document decision provenance (data snapshot, model version, decision rules, config parameters).
- No regulatory filings, execution reporting, or customer advisory obligations.

### Industry Standards & Best Practices

- Controlled access to code, configurations, and data.
- Secure storage of artifacts and outputs.
- No hard-coded secrets or credentials; use environment/config separation.
- Clear separation of configuration, data, and code.

### Required Expertise & Validation

- Expertise in internal fintech controls and data governance.
- Validation focused on **decision auditability** and reproducibility.
- Stakeholder review of decision trails and assumptions (internal only).

### Implementation Considerations

- Deterministic batch runs and explicit config versioning.
- Environment separation (research vs evaluation).
- Transparent reporting to avoid misinterpretation or silent inflation of results.
- Role-based access and controlled read/write permissions.
- Encryption at rest where supported by storage.
- Data retention policies to preserve historical runs for auditability.

### Compliance Matrix (Internal)

- **Regulatory filings:** Not required
- **Execution reporting:** Not required
- **Decision auditability:** Required
- **Data provenance:** Required
- **Secrets management:** Required
- **RBAC:** Required
- **PII handling / GDPR rights:** Not required (no PII)
- **KYC/AML:** Not required

## Developer Tool Specific Requirements

### Project-Type Overview

This is an internal developer tool for decision intelligence in a batch ML trading pipeline. The focus is on composable decision logic, standardized outputs, reproducible evaluation, and workflow acceleration for quant researchers.

### Technical Architecture Considerations

- **Language support:** Python only (MVP/Growth). No multi-language support planned.
- **Packaging/distribution:** keep as a repo module within the existing codebase.
  - Provide a **CLI entrypoint** for core workflows (run evaluation, generate reports, replay run).
  - Optional packaging as a pip package later if cross-repo reuse is needed.
- **IDE/UX integration:** no IDE plugins or dashboards required.
  - Primary UX: batch execution + artifacts.
  - Optional analysis via Jupyter notebooks consuming standardized outputs.
  - Lightweight HTML/markdown reporting is sufficient for MVP.

### Documentation Requirements

**MVP documentation:**
- Architecture overview (decision layer placement in pipeline)
- Decision schema/contracts (inputs/outputs, artifacts, versioning)
- Configuration guide (strategies, horizons, decision rules)
- Run/replay playbook (reproduce, trace, audit)
- Evaluation metrics reference (what is computed and why)

**Growth documentation:**
- Formal API reference (beyond docstrings/README)

### Examples & Templates

Required built-in examples:
- Example strategy configs for at least two horizons (long-term + shorter-term)
- Decision rule templates (position sizing, risk constraints, portfolio constraints)
- Sample evaluation reports showing:
  - Decision trail
  - Regime diagnostics
  - Comparability across runs

### Implementation Considerations

- Keep the decision layer modular and composable within the existing repo.
- Provide stable, machine-readable outputs for notebooks and downstream consumers.
- Ensure CLI workflows are reproducible and traceable via config/version metadata.

## Project Scoping & Phased Development

### MVP Strategy & Philosophy

**MVP Approach:** Problem-Solving MVP  
**Scope Level:** Medium scope (moderate team, balanced features)

### MVP Feature Set (Phase 1)

**Core User Journeys Supported:**
- Quant researcher: diagnose performance drift and iterate using explicit decision logic
- Portfolio decision maker: compare strategies via standardized decision outputs
- Ops/Reviewer: replay and audit decisions with traceability

**Must-Have Capabilities:**
- Explicit decision abstraction layer
- Signal ? decision transformation (positions, sizing, constraints)
- Standardized decision outputs with assumptions/metadata
- Unified evaluation pipeline across strategies/horizons
- Deterministic batch execution with versioned configs + data snapshots
- Decision-level explainability (model + rules)
- Run replay & auditability end-to-end

**What can be simplified in MVP:**
- Portfolio aggregation (static weighting, simple constraints)
- Regime detection (coarse/rule-based)
- Reporting (static CSV/JSON/Markdown/simple plots)
- Strategy config (file-based only)
- Limited number of supported strategy patterns

### Post-MVP Features

**Phase 2 (Growth):**
- Multi-horizon support at scale
- Portfolio-level diagnostics (correlation, drawdown attribution)
- Regime-aware evaluation/comparisons
- Sensitivity & scenario analysis
- Richer reporting/visualization
- Reusable decision rule libraries

**Phase 3 (Expansion):**
- Execution adapters (brokers/bots)
- Containerization/portability
- Advanced automation/scheduling
- Strategy marketplaces/libraries
- Formal APIs for downstream consumers

### Risk Mitigation Strategy

**Technical Risks:**  
Riskiest assumption is that decision logic can be abstracted across diverse strategies without becoming rigid or leaky.  
Mitigation: start with a small number of decision patterns, keep contracts explicit/extensible, validate abstraction usefulness early.

**Market/Strategy Risks:**  
Risk that structure doesn’t materially improve confidence or learning speed.  
Mitigation: focus MVP on comparison/rejection, make explainability and replay unavoidable, validate on real strategies early.

**Resource Risks:**  
If resources shrink, the smallest viable version is:
- One strategy class
- One horizon
- One decision abstraction
- One evaluation path
- Full reproducibility + explainability

## Functional Requirements

### Decision Abstraction & Strategy Definition

- FR1: Quant researcher can define a strategy as a reusable, explicit decision abstraction.
- FR2: Quant researcher can specify strategy horizon (long-term vs shorter-term) in the strategy definition.
- FR3: Quant researcher can define strategy assumptions as structured metadata.
- FR4: Quant researcher can attach decision rules (constraints, sizing rules, eligibility filters) to a strategy.
- FR5: Quant researcher can create multiple strategy variants without altering core pipeline code.
- FR6: System can validate strategy definitions for completeness before evaluation.
- FR7: System can store and retrieve strategy definitions for reuse and comparison.

### Signal ? Decision Transformation

- FR8: System can transform model signals into explicit decision outputs (positions, sizing, constraints).
- FR9: System can apply decision rules deterministically in batch runs.
- FR10: System can annotate decision outputs with the rules and assumptions used.
- FR11: System can produce decision outputs that are independent of model training code.
- FR12: System can apply horizon-specific decision logic based on strategy metadata.

### Evaluation & Comparability

- FR13: System can evaluate strategies using a consistent, standardized metric set.
- FR14: System can compare strategies across different horizons using normalized outputs.
- FR15: System can generate comparable evaluation outputs across runs and configurations.
- FR16: System can support side-by-side evaluation of strategy variants.
- FR17: System can surface decision-level performance signals distinct from model-level metrics.

### Explainability & Decision Traceability

- FR18: System can attach decision-level explanations to each output decision.
- FR19: System can trace any decision to its signal inputs, model outputs, and decision rules.
- FR20: System can provide a decision trail for each run that is auditable and reviewable.
- FR21: System can expose explainability artifacts in machine-readable form for analysis.
- FR22: System can summarize why a strategy was promoted, modified, or discarded.

### Configuration & Versioning

- FR23: Quant researcher can define all strategy, decision, and evaluation settings via versioned config files.
- FR24: System can snapshot configuration versions for each run.
- FR25: System can version decision outputs and evaluation artifacts by run.
- FR26: System can associate each run with data snapshot identifiers.
- FR27: System can enforce deterministic batch execution using fixed inputs and configs.

### Run Orchestration & Replay

- FR28: System can execute batch runs for a given strategy and config.
- FR29: System can replay a historical run end-to-end using stored inputs and configs.
- FR30: System can reconstruct decision outputs for any prior run.
- FR31: System can enumerate available historical runs and their metadata.
- FR32: System can capture run status and results for traceability.

### Reporting & Artifacts

- FR33: System can generate standardized machine-readable outputs (CSV/JSON/Parquet).
- FR34: System can generate human-readable reports (Markdown/HTML/plots).
- FR35: System can produce evaluation summaries suitable for strategy comparison.
- FR36: System can export decision artifacts for downstream analysis workflows.

### Portfolio Views (Basic in MVP)

- FR37: System can aggregate strategy decisions into a basic portfolio view.
- FR38: System can present portfolio-level summaries without execution logic.
- FR39: System can compare portfolio-level outcomes across strategy sets.
- FR40: System can expose portfolio diagnostics as static artifacts.

## Non-Functional Requirements

### Performance

- Batch runs must complete within defined windows:
  - **Intra-day runs:** 30–90 minutes
  - **Daily full evaluations:** 2–4 hours (depending on data range and strategy count)
- Core reports/artifacts must be generated within **5–15 minutes** after a run completes.

### Reliability & Reproducibility

- Runs must be **deterministic and reproducible** given the same data snapshot, config, and model version.
- Outputs must be **functionally identical** (same decisions, metrics, artifacts).
- **Bit-for-bit determinism** is preferred but not mandatory across environments/hardware.

### Security & Access Control

- Enforce **least-privilege** access with basic RBAC roles:
  - Researcher
  - Ops
  - Reviewer (read-only)
- Log access for sensitive actions:
  - Run execution
  - Config changes
  - Artifact access
- No hard-coded secrets; secrets managed via environment or secure config.

### Auditability & Traceability

- Must retain and trace:
  - Config versions (including decision rules & evaluation params)
  - Data snapshots / dataset identifiers
  - Model artifacts & versions
  - Decision outputs and decision trails
  - Run metadata (timestamps, code version/commit hash, environment info)
- Retention:
  - **Default:** 12 months for full run artifacts and decision trails
  - **Extended:** ability to retain longer for promoted strategies (archive/indefinite)

### Scalability

- Support **10–50 strategies**, **2–4 horizons**, **1–6 runs/day**.
- Scale beyond this by adding compute/time, **without architectural changes**.


