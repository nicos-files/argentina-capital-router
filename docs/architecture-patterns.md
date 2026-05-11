# Architecture Patterns

- **Primary pattern:** data/feature pipeline with model training and signal generation stages.
- **Orchestration:** Prefect-based task/flow orchestration (batch or scheduled execution).
- **Configuration:** Hydra + YAML for parameterization and execution flags.
- **Analytics/storage:** DuckDB + Arrow/Parquet for local analytics.
- **ML/Modeling:** Classical ML (scikit-learn) and boosting (XGBoost/LightGBM), with optional deep learning (PyTorch).
- **Explainability:** SHAP/LIME indicates intent to generate interpretable signals.
- **Backtesting/optimization:** Backtesting + vectorbt + cvxpy suggests strategy evaluation and portfolio sizing.
- **Sentiment/alt-data:** Tweepy/Reddit APIs indicate external signal ingestion.
