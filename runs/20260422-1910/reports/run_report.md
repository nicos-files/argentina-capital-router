# Run Report

## Metadata
- run_id: 20260422-1910
- status: SUCCESS
- created_at: 2026-04-23T19:12:34.713590+00:00
- started_at: 2026-04-23T19:12:34.713631+00:00
- completed_at: 2026-04-23T19:12:34.743653+00:00
- config_snapshot_path: /home/naguilar/projects/quant-trading-bot/src/backtest/config_backtest.json

## decision.outputs
- source: runs/20260422-1910/artifacts/decision.outputs.v1.0.0.json
- strategy_id: quant_trading_bot
- horizon: SHORT

```json
[
  {
    "asset_id": "AMD",
    "outputs": {
      "asof_date": "2026-04-21",
      "decision_type": "intraday",
      "empirical_hit_rate": 0.993289,
      "empirical_mean_return": 0.021638,
      "empirical_observations": 149,
      "expected_return_gross_pct": 0.021038,
      "justificacion": "model_score=0.973208 day=2026-04-21 | empirical_mean=0.021638 | empirical_hit=0.993289 | empirical_n=149",
      "model_score": 0.973208,
      "peso_pct": 49.655509,
      "selection_score": 0.02047432
    },
    "signal": 1.0
  },
  {
    "asset_id": "JPM",
    "outputs": {
      "asof_date": "2026-04-21",
      "decision_type": "intraday",
      "empirical_hit_rate": 1.0,
      "empirical_mean_return": 0.011419,
      "empirical_observations": 152,
      "expected_return_gross_pct": 0.012018,
      "justificacion": "model_score=0.986067 day=2026-04-21 | empirical_mean=0.011419 | empirical_hit=1.000000 | empirical_n=152",
      "model_score": 0.986067,
      "peso_pct": 28.73985,
      "selection_score": 0.01185022
    },
    "signal": 1.0
  },
  {
    "asset_id": "MSFT",
    "outputs": {
      "asof_date": "2026-04-21",
      "decision_type": "intraday",
      "empirical_hit_rate": 0.992537,
      "empirical_mean_return": 0.007869,
      "empirical_observations": 134,
      "expected_return_gross_pct": 0.008999,
      "justificacion": "model_score=0.989962 day=2026-04-21 | empirical_mean=0.007869 | empirical_hit=0.992537 | empirical_n=134",
      "model_score": 0.989962,
      "peso_pct": 21.604641,
      "selection_score": 0.00890818
    },
    "signal": 1.0
  }
]
```

## evaluation.metrics
- source: runs/20260422-1910/artifacts/evaluation.metrics.v1.0.0.json
- strategy_id: quant_trading_bot
- horizon: SHORT

| metric | value |
| --- | --- |
| max_drawdown | 0.01651345853713706 |
| operations | 906 |
| ret_daily_mean | 0.013366073712093971 |
| ret_total | 27.551854345362393 |
