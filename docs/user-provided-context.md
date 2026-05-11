Focus especially on:
- src/orchestrator/ (data_orchestrator and execution flow)
- src/execution/ (ingest, process, strategy, backtest modules)
- src/pipeline/ or equivalent data/feature pipeline code
- strategy_agent.py and backtest-related logic
- Any feature engineering or signal generation code
- requirements.txt for dependencies that hint at modeling, data, or execution
- Configuration patterns (if any) that define execution order, flags, or parameters

The orchestrator and execution modules are critical, as the goal is to evolve this from a data pipeline into an investment recommender.
