from __future__ import annotations

from typing import Any

import pandas as pd

from src.decision_intel.contracts.recommendations.recommendation_models import RecommendationOutput

from .base import EngineContext, EngineDiagnostics, EngineResult


class LongTermPortfolioEngine:
    name = "long_term_portfolio"
    horizon = "long_term"

    def run(self, context: EngineContext) -> EngineResult:
        diagnostics = EngineDiagnostics(engine_name=self.name)
        decision_rows = self._build_candidates(context, diagnostics)
        output = self._to_recommendation_output(context, decision_rows)
        diagnostics.metadata["decision_rows"] = decision_rows
        return EngineResult(
            engine_name=self.name,
            horizon=self.horizon,
            recommendations=output,
            diagnostics=diagnostics,
        )

    def _build_candidates(
        self,
        context: EngineContext,
        diagnostics: EngineDiagnostics,
    ) -> list[dict[str, Any]]:
        current_df = context.prices
        history_df = context.metadata.get("history_df")
        asof_date = context.metadata.get("asof_date") or context.as_of.strftime("%Y-%m-%d")
        top_k = int(context.metadata.get("top_k", 10))

        if not context.universe:
            diagnostics.warnings.append("Empty universe; long-term engine skipped.")
            return []
        if current_df is None or getattr(current_df, "empty", True):
            diagnostics.warnings.append("Current feature frame missing or empty; long-term engine skipped.")
            return []

        diagnostics.candidates_seen = len(current_df.index)

        # TODO: move the helper logic out of run_all.py in a later slice.
        from src.tools.run_all import _build_long_term_candidates

        rows = _build_long_term_candidates(
            current_df=current_df,
            history_df=history_df if isinstance(history_df, pd.DataFrame) else pd.DataFrame(),
            asof_date=asof_date,
            top_k=top_k,
        )
        diagnostics.candidates_scored = len(rows)
        diagnostics.candidates_rejected = max(diagnostics.candidates_seen - diagnostics.candidates_scored, 0)
        if history_df is None or getattr(history_df, "empty", True):
            diagnostics.warnings.append("History frame missing or empty; long-term recommendations may be empty.")
        return rows

    def _to_recommendation_output(
        self,
        context: EngineContext,
        rows: list[dict[str, Any]],
    ) -> RecommendationOutput:
        items = [self._candidate_to_item(context, row) for row in rows]
        return RecommendationOutput.build(
            run_id=context.run_id,
            horizon=self.horizon.upper(),
            asof_date=context.metadata.get("asof_date") or context.as_of.strftime("%Y-%m-%d"),
            policy_id=self.name,
            policy_version="1",
            constraints=[],
            sizing_rule="engine.boundary",
            recommendations=items,
            cash_summary={},
            cash_policy="engine.noop",
            execution_date=context.metadata.get("execution_date"),
            execution_hour=context.metadata.get("execution_hour"),
            metadata={"engine_name": self.name},
        )

    def _candidate_to_item(self, context: EngineContext, row: dict[str, Any]) -> dict[str, Any]:
        ticker = str(row.get("ticker") or "").strip().upper()
        return {
            "ticker": ticker,
            "asset_id": ticker,
            "horizon": self.horizon,
            "action": "SKIP",
            "weight": float(row.get("peso_pct") or 0.0) / 100.0,
            "usd_target": 0.0,
            "usd_target_effective": 0.0,
            "broker_selected": "",
            "current_qty": 0.0,
            "qty_target": 0.0,
            "delta_qty": 0.0,
            "order_side": None,
            "order_type": "NONE",
            "time_in_force": "",
            "order_qty": 0.0,
            "order_notional_usd": 0.0,
            "order_notional_ccy": 0.0,
            "min_notional_usd": 0.0,
            "order_status": "NO_ORDER",
            "cash_available_usd": context.cash,
            "cash_used_usd": 0.0,
            "min_capital_viable_usd": None,
            "price_used": None,
            "price_source": "engine.long_term",
            "currency": "USD",
            "fx_rate_used": None,
            "fx_rate_source": "",
            "lot_size": 1,
            "allow_fractional": True,
            "expected_return_gross_pct": float(row.get("expected_return_gross_pct") or 0.0),
            "expected_return_net_pct": 0.0,
            "expected_return_net_usd": 0.0,
            "expected_return_source": "engine_candidate",
            "fees_estimated_usd": 0.0,
            "fees_one_way": 0.0,
            "fees_round_trip": 0.0,
            "broker_costs": {},
            "reason": str(row.get("justificacion") or ""),
            "policy_id": self.name,
            "policy_version": "1",
            "constraints": [],
            "sizing_rule": "engine.boundary",
            "asof_date": context.metadata.get("asof_date") or context.as_of.strftime("%Y-%m-%d"),
            "execution_date": context.metadata.get("execution_date"),
            "execution_hour": context.metadata.get("execution_hour"),
            "peso_pct": row.get("peso_pct"),
            "model_score": row.get("model_score"),
            "selection_score": row.get("selection_score"),
            "empirical_mean_return": row.get("empirical_mean_return"),
            "empirical_hit_rate": row.get("empirical_hit_rate"),
            "empirical_observations": row.get("empirical_observations"),
        }
