# Run Report

## Metadata
- run_id: 20260422-1820
- status: SUCCESS
- created_at: 2026-04-22T20:03:34.838311+00:00
- started_at: 2026-04-22T20:03:34.838341+00:00
- completed_at: 2026-04-22T20:03:34.855889+00:00
- config_snapshot_path: /home/naguilar/projects/quant-trading-bot/src/backtest/config_backtest.json

## decision.outputs
- source: runs/20260422-1820/artifacts/decision.outputs.v1.0.0.json
- strategy_id: quant_trading_bot
- horizon: SHORT

```json
[
  {
    "asset_id": "NVDA",
    "outputs": {
      "asof_date": "2026-04-21",
      "decision_type": "intraday",
      "justificacion": "model_score=0.973459 day=2026-04-21",
      "model_score": 0.973459,
      "peso_pct": 13.087378
    },
    "signal": 1.0
  },
  {
    "asset_id": "INTC",
    "outputs": {
      "asof_date": "2026-04-21",
      "decision_type": "intraday",
      "justificacion": "model_score=0.894353 day=2026-04-21",
      "model_score": 0.894353,
      "peso_pct": 12.023856
    },
    "signal": 1.0
  },
  {
    "asset_id": "META",
    "outputs": {
      "asof_date": "2026-04-21",
      "decision_type": "intraday",
      "justificacion": "model_score=0.861257 day=2026-04-21",
      "model_score": 0.861257,
      "peso_pct": 11.578911
    },
    "signal": 1.0
  },
  {
    "asset_id": "JPM",
    "outputs": {
      "asof_date": "2026-04-21",
      "decision_type": "intraday",
      "justificacion": "model_score=0.837475 day=2026-04-21",
      "model_score": 0.837475,
      "peso_pct": 11.259176
    },
    "signal": 1.0
  },
  {
    "asset_id": "MA",
    "outputs": {
      "asof_date": "2026-04-21",
      "decision_type": "intraday",
      "justificacion": "model_score=0.836912 day=2026-04-21",
      "model_score": 0.836912,
      "peso_pct": 11.251611
    },
    "signal": 1.0
  },
  {
    "asset_id": "DIS",
    "outputs": {
      "asof_date": "2026-04-21",
      "decision_type": "intraday",
      "justificacion": "model_score=0.834914 day=2026-04-21",
      "model_score": 0.834914,
      "peso_pct": 11.224745
    },
    "signal": 1.0
  },
  {
    "asset_id": "NFLX",
    "outputs": {
      "asof_date": "2026-04-21",
      "decision_type": "intraday",
      "justificacion": "model_score=0.695208 day=2026-04-21",
      "model_score": 0.695208,
      "peso_pct": 9.346513
    },
    "signal": 1.0
  },
  {
    "asset_id": "TSLA",
    "outputs": {
      "asof_date": "2026-04-21",
      "decision_type": "intraday",
      "justificacion": "model_score=0.681994 day=2026-04-21",
      "model_score": 0.681994,
      "peso_pct": 9.168861
    },
    "signal": 1.0
  },
  {
    "asset_id": "V",
    "outputs": {
      "asof_date": "2026-04-21",
      "decision_type": "intraday",
      "justificacion": "model_score=0.508357 day=2026-04-21",
      "model_score": 0.508357,
      "peso_pct": 6.834449
    },
    "signal": 1.0
  },
  {
    "asset_id": "GOOGL",
    "outputs": {
      "asof_date": "2026-04-21",
      "decision_type": "intraday",
      "justificacion": "model_score=0.314225 day=2026-04-21",
      "model_score": 0.314225,
      "peso_pct": 4.2245
    },
    "signal": 1.0
  }
]
```

## evaluation.metrics
- source: runs/20260422-1820/artifacts/evaluation.metrics.v1.0.0.json
- strategy_id: quant_trading_bot
- horizon: SHORT

| metric | value |
| --- | --- |
| max_drawdown | 0.5165387932991607 |
| operations | 1240 |
| ret_daily_mean | -0.0019189073286687804 |
| ret_total | -0.3956050370530252 |
