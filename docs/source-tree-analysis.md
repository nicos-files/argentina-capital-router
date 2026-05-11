# Source Tree Analysis (Main)

```
quant-trading-bot/
+-- src/
¦   +-- orchestrator/
¦   ¦   +-- data_orchestrator.py        # ETL orchestration, state tracking, daily consolidation
¦   +-- execution/
¦   ¦   +-- run_pipeline.py             # Legacy pipeline runner (imports missing strategy_llm_agent)
¦   ¦   +-- debugs_agent.py             # Debug helper (agent-related)
¦   ¦   +-- ingest/
¦   ¦   ¦   +-- fetch_prices.py         # Price ingestion via Stooq
¦   ¦   ¦   +-- alphaV_fetcher.py       # Price ingestion via Alpha Vantage
¦   ¦   ¦   +-- ingest_fundamentals.py  # Fundamentals ingestion (Alpha Vantage + Finnhub)
¦   ¦   ¦   +-- ingest_sentiment.py     # News/Reddit ingestion (NewsAPI, Reddit)
¦   ¦   ¦   +-- scrape_news.py          # RSS-based news scraping (Ambito/Cronista)
¦   ¦   ¦   +-- investing_scraper.py    # Additional scraping (not reviewed)
¦   ¦   +-- process/
¦   ¦   ¦   +-- process_prices.py       # Clean and normalize raw prices
¦   ¦   ¦   +-- process_indicators.py   # Technical indicators from processed prices
¦   ¦   ¦   +-- process_fundamentals.py # Normalize fundamentals from raw sources
¦   ¦   ¦   +-- relevance_filter.py     # LLM-based relevance filtering for sentiment
¦   ¦   ¦   +-- process_sentiment.py    # LLM-based sentiment scoring
¦   ¦   +-- curated/
¦   ¦       +-- daily_consolidator.py   # Consolidate daily processed outputs
¦   +-- pipeline/
¦   ¦   +-- feature_engineering.py      # Merge indicators + fundamentals + sentiment into features
¦   ¦   +-- train_model.py              # Train ML models (XGBoost classifiers/regressors)
¦   ¦   +-- generate_signals.py          # Score signals + expected returns + risk
¦   +-- backtest/
¦   ¦   +-- config_backtest.json        # Backtest parameters
¦   ¦   +-- prepare_data.py             # Build dataset + predictions for backtest
¦   ¦   +-- run_backtest.py             # Execute daily backtest loop
¦   ¦   +-- compute_metrics.py          # Compute backtest metrics
¦   ¦   +-- plot_equity.py              # Plot equity curve
¦   ¦   +-- backtest_strategy.py        # Backtest entrypoint
¦   +-- features/
¦   ¦   +-- technical_indicators.py     # Alternate indicator calculator (raw inputs)
¦   +-- agents/
¦   ¦   +-- agent_definitions.py        # Agent wiring + env loading
¦   ¦   +-- orchestrator_agent.py       # End-to-end orchestration and decisions
¦   ¦   +-- sentiment_agent.py          # Sentiment logic
¦   ¦   +-- long_term_agent.py          # Long-term recommendation agent
¦   ¦   +-- intraday_agent.py           # Intraday recommendation agent
¦   ¦   +-- strategy_agent.py           # OpenAI strategy agent
¦   ¦   +-- user_agent.py               # UI/presentation helper
¦   ¦   +-- llm_wrappers/
¦   ¦       +-- gpt4all_agent.py        # Local LLM wrapper
¦   +-- utils/
¦       +-- execution_context.py        # Date/hour and path helpers
¦       +-- llm_logger.py               # LLM interaction logging
¦       +-- cache_manager.py            # Cache for relevance filtering
+-- simulations/                         # Backtest outputs (csv/png/json)
+-- tests/                               # Tests (not reviewed)
+-- scripts/                             # Utility scripts (not reviewed)
+-- _bmad/                               # BMAD Method workflows
+-- _bmad-output/                        # BMAD outputs
+-- README.md
+-- requirements.txt
+-- main.py                              # References missing src/utils/hello.py
```
