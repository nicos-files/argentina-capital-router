# Run Report

## Metadata
- run_id: 20260422-1940
- status: SUCCESS
- created_at: 2026-04-23T20:49:30.036500+00:00
- started_at: 2026-04-23T20:49:30.036555+00:00
- completed_at: 2026-04-23T20:49:30.088458+00:00
- config_snapshot_path: /home/naguilar/projects/quant-trading-bot/src/backtest/config_backtest.json

## decision.outputs
- source: runs/20260422-1940/artifacts/decision.outputs.v1.0.0.json
- strategy_id: quant_trading_bot
- horizon: SHORT

```json
[
  {
    "asset_id": "JPM",
    "outputs": {
      "asof_date": "2026-04-21",
      "decision_type": "intraday",
      "empirical_hit_rate": 1.0,
      "empirical_mean_return": 0.008709,
      "empirical_observations": 169,
      "expected_return_gross_pct": 0.00886,
      "justificacion": "model_score=0.986599 day=2026-04-21 | empirical_mean=0.008709 | empirical_hit=1.000000 | empirical_n=169 | oos_trade_mean=0.007887 | oos_trade_hit=1.000000 | oos_trade_n=76",
      "model_score": 0.986599,
      "peso_pct": 40.38898,
      "selection_score": 0.01311215
    },
    "signal": 1.0
  },
  {
    "asset_id": "V",
    "outputs": {
      "asof_date": "2026-04-21",
      "decision_type": "intraday",
      "empirical_hit_rate": 0.993243,
      "empirical_mean_return": 0.006306,
      "empirical_observations": 148,
      "expected_return_gross_pct": 0.006762,
      "justificacion": "model_score=0.995793 day=2026-04-21 | empirical_mean=0.006306 | empirical_hit=0.993243 | empirical_n=148 | oos_trade_mean=0.004581 | oos_trade_hit=1.000000 | oos_trade_n=75",
      "model_score": 0.995793,
      "peso_pct": 31.113012,
      "selection_score": 0.01010074
    },
    "signal": 1.0
  },
  {
    "asset_id": "MSFT",
    "outputs": {
      "asof_date": "2026-04-21",
      "decision_type": "intraday",
      "empirical_hit_rate": 1.0,
      "empirical_mean_return": 0.005673,
      "empirical_observations": 135,
      "expected_return_gross_pct": 0.006249,
      "justificacion": "model_score=0.986990 day=2026-04-21 | empirical_mean=0.005673 | empirical_hit=1.000000 | empirical_n=135 | oos_trade_mean=0.004468 | oos_trade_hit=1.000000 | oos_trade_n=76",
      "model_score": 0.98699,
      "peso_pct": 28.498008,
      "selection_score": 0.00925179
    },
    "signal": 1.0
  }
]
```

## evaluation.metrics
- source: runs/20260422-1940/artifacts/evaluation.metrics.v1.0.0.json
- strategy_id: quant_trading_bot
- horizon: SHORT

| metric | value |
| --- | --- |
| evaluated_rows | 1339 |
| evaluation_mode | oos_holdout |
| max_drawdown | 0.003349091635602611 |
| operations | 267 |
| purge_days | 1 |
| purge_end_date | 2026-02-04 |
| purge_start_date | 2026-02-04 |
| ret_daily_mean | 0.0033640293535599115 |
| ret_total | 0.29065574425694396 |
| selected_features_count | 31 |
| target_definition | signal_at_close_t__enter_open_t_plus_1__exit_close_t_plus_1 |
| test_days | 76 |
| test_end_date | 2026-04-21 |
| test_start_date | 2026-02-05 |
| train_days | 176 |
| train_end_date | 2026-02-03 |
| train_start_date | 2025-08-12 |
