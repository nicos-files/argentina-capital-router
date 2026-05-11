# Project Documentation Index

## Project Overview

- **Type:** monolith (data pipeline)
- **Primary Language:** Python
- **Architecture:** Batch ETL + ML + signal generation

## Quick Reference

- **Tech Stack:** Python, pandas/numpy, XGBoost/LightGBM, Prefect, DuckDB
- **Entry Point:** src/run.py
- **Architecture Pattern:** Data/feature pipeline

## Generated Documentation

- [Project Overview](./project-overview.md)
- [Architecture](./architecture.md)
- [Source Tree Analysis](./source-tree-analysis.md)
- [Component Inventory](./component-inventory.md)
- [Development Guide](./development-guide.md)
- [Deployment Configuration](./deployment-configuration.md)
- [Contribution Guidelines](./contribution-guidelines.md)
- [Data Models](./data-models.md)
- [Technology Stack](./technology-stack.md)
- [Architecture Patterns](./architecture-patterns.md)
- [Comprehensive Analysis](./comprehensive-analysis-main.md)

## Existing Documentation

- [README](../README.md) - High-level pipeline overview (may be outdated)
- [Project Structure](./project-structure.md)
- [Project Parts Metadata](./project-parts-metadata.json)
- [Project Scan Report](./project-scan-report.json)
- [Development Instructions](./development-instructions.md)
- [User Provided Context](./user-provided-context.md)

## Getting Started

1. Review the architecture and data model docs
2. Run the ETL pipeline with `python -m src.orchestrator.data_orchestrator`
3. Generate features and signals with the pipeline modules
4. Use `python -m src.run` for end-to-end orchestration
