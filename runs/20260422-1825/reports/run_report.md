# Run Report

## Metadata
- run_id: 20260422-1825
- status: SUCCESS
- created_at: 2026-04-22T20:12:03.730290+00:00
- started_at: 2026-04-22T20:12:03.730290+00:00
- completed_at: 2026-04-22T20:12:04.816659+00:00
- config_snapshot_path: \\wsl.localhost\Ubuntu\home\naguilar\projects\quant-trading-bot\src\backtest\config_backtest.json

## decision.outputs
- source: runs\20260422-1825\artifacts\decision.outputs.v1.0.0.json
- strategy_id: quant_trading_bot
- horizon: SHORT

```json
[
  {
    "asset_id": "JPM",
    "outputs": {
      "asof_date": "2026-04-21",
      "decision_type": "intraday",
      "empirical_hit_rate": 0.884298,
      "empirical_mean_return": 0.008248,
      "empirical_observations": 121,
      "expected_return_gross_pct": 0.006969,
      "justificacion": "model_score=0.837475 day=2026-04-21 | empirical_mean=0.008248 | empirical_hit=0.884298 | empirical_n=121",
      "model_score": 0.837475,
      "peso_pct": 100.0,
      "selection_score": 0.00583669
    },
    "signal": 1.0
  }
]
```

## evaluation.metrics
- source: runs\20260422-1825\artifacts\evaluation.metrics.v1.0.0.json
- strategy_id: quant_trading_bot
- horizon: SHORT

| metric | value |
| --- | --- |
| max_drawdown | 0.5165387932991607 |
| operations | 1240 |
| ret_daily_mean | -0.0019189073286687804 |
| ret_total | -0.3956050370530252 |
