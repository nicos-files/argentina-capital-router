# Run Report

## Metadata
- run_id: 20260119-1519
- status: SUCCESS
- created_at: 2026-01-21T18:58:15.852025+00:00
- started_at: 2026-01-21T18:58:15.852131+00:00
- completed_at: 2026-01-21T18:58:15.853990+00:00
- config_snapshot_path: /home/naguilar/projects/quant-trading-bot/src/backtest/config_backtest.json

## decision.outputs
- source: runs/20260119-1519/artifacts/decision.outputs.v1.0.0.json
- strategy_id: quant_trading_bot
- horizon: SHORT

```json
[
  {
    "asset_id": "NVDA",
    "outputs": {
      "asof_date": "2026-01-14",
      "decision_type": "intraday",
      "justificacion": "model_score=0.942329 day=2026-01-14",
      "model_score": 0.942329,
      "peso_pct": 11.673162
    },
    "signal": 1.0
  },
  {
    "asset_id": "TSLA",
    "outputs": {
      "asof_date": "2026-01-14",
      "decision_type": "intraday",
      "justificacion": "model_score=0.921661 day=2026-01-14",
      "model_score": 0.921661,
      "peso_pct": 11.417139
    },
    "signal": 1.0
  },
  {
    "asset_id": "NFLX",
    "outputs": {
      "asof_date": "2026-01-14",
      "decision_type": "intraday",
      "justificacion": "model_score=0.884233 day=2026-01-14",
      "model_score": 0.884233,
      "peso_pct": 10.953496
    },
    "signal": 1.0
  },
  {
    "asset_id": "DIS",
    "outputs": {
      "asof_date": "2026-01-14",
      "decision_type": "intraday",
      "justificacion": "model_score=0.878833 day=2026-01-14",
      "model_score": 0.878833,
      "peso_pct": 10.886599
    },
    "signal": 1.0
  },
  {
    "asset_id": "META",
    "outputs": {
      "asof_date": "2026-01-14",
      "decision_type": "intraday",
      "justificacion": "model_score=0.826503 day=2026-01-14",
      "model_score": 0.826503,
      "peso_pct": 10.23836
    },
    "signal": 1.0
  },
  {
    "asset_id": "INTC",
    "outputs": {
      "asof_date": "2026-01-14",
      "decision_type": "intraday",
      "justificacion": "model_score=0.816281 day=2026-01-14",
      "model_score": 0.816281,
      "peso_pct": 10.111737
    },
    "signal": 1.0
  },
  {
    "asset_id": "V",
    "outputs": {
      "asof_date": "2026-01-14",
      "decision_type": "intraday",
      "justificacion": "model_score=0.807973 day=2026-01-14",
      "model_score": 0.807973,
      "peso_pct": 10.008813
    },
    "signal": 1.0
  },
  {
    "asset_id": "JPM",
    "outputs": {
      "asof_date": "2026-01-14",
      "decision_type": "intraday",
      "justificacion": "model_score=0.745190 day=2026-01-14",
      "model_score": 0.74519,
      "peso_pct": 9.231083
    },
    "signal": 1.0
  },
  {
    "asset_id": "AMD",
    "outputs": {
      "asof_date": "2026-01-14",
      "decision_type": "intraday",
      "justificacion": "model_score=0.679848 day=2026-01-14",
      "model_score": 0.679848,
      "peso_pct": 8.421655
    },
    "signal": 1.0
  },
  {
    "asset_id": "GOOGL",
    "outputs": {
      "asof_date": "2026-01-14",
      "decision_type": "intraday",
      "justificacion": "model_score=0.569761 day=2026-01-14",
      "model_score": 0.569761,
      "peso_pct": 7.057956
    },
    "signal": 1.0
  }
]
```

## evaluation.metrics
- source: runs/20260119-1519/artifacts/evaluation.metrics.v1.0.0.json
- strategy_id: quant_trading_bot
- horizon: SHORT

| metric | value |
| --- | --- |
| max_drawdown | 0.15526547399901194 |
| operations | 1218 |
| ret_daily_mean | 0.0010998901139000284 |
| ret_total | 0.2876905229541118 |
