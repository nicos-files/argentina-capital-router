from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Tuple

import numpy as np
import pandas as pd

from src.decision_intel.contracts.metadata_models import CURRENT_SCHEMA_VERSION
from src.decision_intel.execution.execution_engine import execute_plan
from src.decision_intel.exports.artifact_exporter import export_artifacts
from src.decision_intel.integrations.quant_trading_bot_adapter import build_decision_intel_artifacts
from src.decision_intel.policies.topk_net_after_fees import CAPITAL_USD
from src.engines import EngineContext, IntradayCryptoEngine, LongTermPortfolioEngine
from src.market_data.crypto_symbols import enabled_crypto_symbols, load_crypto_universe_config
from src.market_data.providers import BinanceSpotMarketDataProvider

ROOT = Path(__file__).resolve().parents[2]
FEATURES_BASE = ROOT / "data" / "processed" / "features"
CRYPTO_UNIVERSE_PATH = ROOT / "config" / "market_universe" / "crypto.json"
INTRADAY_MODEL_PATH = ROOT / "models" / "xgb_clf_intraday.pkl"
INTRADAY_MODEL_FALLBACK_PATH = ROOT / "models" / "xgb_clf_futuro.pkl"
LONG_TERM_MODEL_PATH = ROOT / "models" / "xgb_reg_long_term.pkl"
FINAL_DECISION_PATH = ROOT / "data" / "results" / "final_decision.json"
BACKTEST_SUMMARY_PATH = ROOT / "simulations" / "backtest_summary.json"
SIMULATE_SUMMARY_PATH = ROOT / "simulations" / "simulate_summary.json"
DECISION_HISTORY_DAYS = 252
DECISION_MIN_SCORE = 0.55
DECISION_MIN_OBSERVATIONS = 20
DECISION_MIN_HIT_RATE = 0.55
DECISION_MIN_EXPECTED_RETURN = 0.003
DECISION_SHRINKAGE = 20.0
OOS_TICKER_SUMMARY_PATH = ROOT / "simulations" / "simulate_ticker_summary.json"
OOS_TICKER_MIN_TRADES = 12
OOS_TICKER_MIN_MEAN_RET = 0.001
OOS_TICKER_MIN_HIT_RATE = 0.55
LONG_TERM_MIN_PREDICTED_RETURN = 0.01
LONG_TERM_MIN_OBSERVATIONS = 20
LONG_TERM_MIN_HIT_RATE = 0.55
LONG_TERM_MIN_EXPECTED_RETURN = 0.01
LONG_TERM_SHRINKAGE = 20.0


def run_all(
    date: str,
    hour: str,
    mode: str = "offline",
    timeout_sec: int | None = None,
    emit_recommendations: bool = True,
    skip_train: bool = False,
    skip_backtest: bool = False,
    skip_simulate: bool = False,
    dry_run: bool = False,
    skip_live_ingest: bool = False,
    execute: bool = False,
    paper: bool = True,
    kill_switch: str | None = None,
) -> None:
    timeout = _resolve_timeout(timeout_sec)
    run_id = date.replace("-", "") + "-" + hour
    requested_date = _parse_date(date)

    commands = _build_orchestrator_cmd(date, hour, mode, skip_live_ingest)
    if dry_run:
        _print_dry_run(commands, requested_date, skip_backtest, skip_simulate, timeout)
        return

    _run_cmd(commands, "orchestrator", timeout, cwd=ROOT, retries=1)

    asof_date, features_path = _select_asof_date(requested_date)
    print(f"[RUN-ALL] asof_date={asof_date} features_path={features_path}")

    if not skip_backtest:
        backtest_cmd = [
            sys.executable,
            "-m",
            "src.backtest.backtest_strategy",
            "--date",
            asof_date,
            "--lookback-days",
            "252",
        ]
        _run_cmd(backtest_cmd, "backtest", timeout, cwd=ROOT)

    if not skip_simulate:
        simulate_cmd = [
            sys.executable,
            "-m",
            "src.simulations.simulate_estrategy",
            "--date",
            asof_date,
        ]
        _run_cmd(simulate_cmd, "simulate", timeout, cwd=ROOT)

    _generate_final_decision(
        features_path=features_path,
        asof_date=asof_date,
        execution_date=date,
        execution_hour=hour,
        top_k=10,
    )

    _validate_required_outputs(
        run_id=run_id,
        asof_date=asof_date,
        emit_recommendations=emit_recommendations,
        skip_backtest=skip_backtest,
        skip_simulate=skip_simulate,
    )

    try:
        build_decision_intel_artifacts(
            run_id=run_id,
            base_path="runs",
            final_decision_path=str(FINAL_DECISION_PATH),
            backtest_summary_path=str(BACKTEST_SUMMARY_PATH),
            date=date,
            hour=hour,
            emit_recommendations=emit_recommendations,
        )
    except Exception as exc:
        print(f"[ERROR] step=adapter error={exc}")
        raise RuntimeError("adapter failed") from exc

    if execute:
        if mode != "live":
            raise ValueError("execute requires --mode live")
        if not emit_recommendations:
            raise ValueError("execute requires --emit-recommendations")
        results_path, results_entry, snapshot_before_path, snapshot_before_entry, snapshot_path, snapshot_entry = execute_plan(
            run_id=run_id,
            base_path="runs",
            paper=paper,
            kill_switch_path=kill_switch,
        )
        _update_manifest_entries(run_id, [results_entry, snapshot_before_entry, snapshot_entry])
        export_artifacts(run_id=run_id, base_path="runs")

    _validate_run_outputs(run_id, emit_recommendations)
    if emit_recommendations:
        _print_recommendation_summary(run_id)

    print("[RUN-ALL] SUCCESS")
    print(f"- execution_date: {date}")
    print(f"- execution_hour: {hour}")
    print(f"- asof_date: {asof_date}")
    print(f"- run_id: {run_id}")
    print(f"- final_decision: {FINAL_DECISION_PATH}")
    print(f"- backtest_summary: {BACKTEST_SUMMARY_PATH}")
    if SIMULATE_SUMMARY_PATH.exists():
        print(f"- simulate_summary: {SIMULATE_SUMMARY_PATH}")
    print(f"- manifest: {ROOT / 'runs' / run_id / 'manifests' / f'run_manifest.v{CURRENT_SCHEMA_VERSION}.json'}")

    if skip_train:
        print("[RUN-ALL] skip_train requested (no-op).")
    _print_bmad_review()


def _print_recommendation_summary(run_id: str) -> None:
    run_root = ROOT / "runs" / run_id
    rec_path = run_root / "artifacts" / f"recommendation.outputs.v{CURRENT_SCHEMA_VERSION}.json"
    if not rec_path.exists():
        print("[RUN-ALL] recommendation summary skipped: artifact missing")
        return
    payload = json.loads(rec_path.read_text(encoding="utf-8"))
    items = payload.get("recommendations", [])
    cash_summary = payload.get("cash_summary", {})
    horizons = sorted({item.get("horizon") for item in items if item.get("horizon")})
    for horizon in horizons:
        horizon_items = [item for item in items if item.get("horizon") == horizon]
        buy_items = [item for item in horizon_items if item.get("action") == "BUY"]
        total_usd = sum(float(item.get("usd_target_effective") or 0.0) for item in buy_items)
        weight_sum = sum(float(item.get("weight") or 0.0) for item in buy_items)
        capital = CAPITAL_USD.get(horizon, 0.0)
        cash_info = cash_summary.get(horizon, {}) if isinstance(cash_summary, dict) else {}
        cash_retained = cash_info.get("cash_retained_usd")
        print(
            f"[RUN-ALL] {horizon} summary: capital={capital} buy_count={len(buy_items)} "
            f"total_usd_effective={total_usd:.2f} buy_weight_sum={weight_sum:.6f} "
            f"cash_retained_usd={cash_retained if cash_retained is not None else 'n/a'}"
        )
        top_items = sorted(
            buy_items,
            key=lambda item: float(item.get("expected_return_net_pct") or 0.0),
            reverse=True,
        )[:5]
        for item in top_items:
            score = _extract_score(item.get("reason"))
            print(
                f"- {item.get('asset_id')} score={score} action={item.get('action')} "
                f"qty={item.get('qty_target')} usd={float(item.get('usd_target_effective') or 0.0):.2f} "
                f"gross_pct={float(item.get('expected_return_gross_pct') or 0.0):.6f} "
                f"net_pct={float(item.get('expected_return_net_pct') or 0.0):.6f} "
                f"fees={float(item.get('fees_estimated_usd') or 0.0):.2f} "
                f"broker={item.get('broker_selected')} currency={item.get('currency')}"
            )


def _extract_score(reason: str | None) -> str:
    if not reason:
        return "n/a"
    marker = "model_score="
    if marker not in reason:
        return "n/a"
    try:
        value = reason.split(marker, 1)[1].split()[0]
        return value
    except Exception:
        return "n/a"


def _print_bmad_review() -> None:
    print("BMAD Review – Missing for Full Automation")
    print("- BLOCKER: real-time market prices + quote validation")
    print("- BLOCKER: broker API auth + order placement")
    print("- BLOCKER: order state reconciliation (fills/partials/cancel)")
    print("- BLOCKER: position/cash reconciliation with broker")
    print("- BLOCKER: risk kill-switch and circuit breakers")
    print("- NON-BLOCKER: FX rates feed for non-USD execution (blocked without source)")
    print("- NON-BLOCKER: slippage/market impact modeling")
    print("- FUTURE IMPROVEMENT: portfolio-level optimization and sizing")
    print("- FUTURE IMPROVEMENT: calibrated expected-return mapping")


def _update_manifest_entries(run_id: str, entries: Iterable[dict[str, Any]]) -> None:
    run_root = ROOT / "runs" / run_id
    manifest_path = run_root / "manifests" / f"run_manifest.v{CURRENT_SCHEMA_VERSION}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifact_index = manifest.get("artifact_index", [])
    for entry in entries:
        if not entry:
            continue
        _upsert_artifact(artifact_index, entry)
    manifest["artifact_index"] = artifact_index
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )


def _upsert_artifact(artifact_index: list[dict[str, Any]], candidate: dict[str, Any]) -> None:
    for index, entry in enumerate(artifact_index):
        if (
            entry.get("name") == candidate.get("name")
            and entry.get("type") == candidate.get("type")
            and entry.get("path") == candidate.get("path")
        ):
            artifact_index[index] = {**entry, **candidate}
            return
    artifact_index.append(candidate)


def _build_orchestrator_cmd(date: str, hour: str, mode: str, skip_live_ingest: bool) -> list[str]:
    if mode not in {"live", "offline"}:
        raise ValueError("mode must be live or offline")
    cmd = [
        sys.executable,
        "-m",
        "src.orchestrator.data_orchestrator",
        "--date",
        date,
        "--hour",
        hour,
    ]
    if mode == "offline":
        cmd.extend(
            [
                "--skip-alpha",
                "--skip-fetch_prices",
                "--skip-fundamentals",
                "--skip-sentiment",
                "--skip-relevance",
            ]
        )
    if mode == "live" and skip_live_ingest:
        cmd.extend(
            [
                "--skip-alpha",
                "--skip-fetch_prices",
                "--skip-fundamentals",
                "--skip-sentiment",
                "--skip-relevance",
                "--skip-process_prices",
            ]
        )
    return cmd


def _resolve_timeout(timeout_sec: int | None) -> int:
    if timeout_sec is not None:
        return int(timeout_sec)
    env_value = os.getenv("ETL_SUBPROCESS_TIMEOUT_SEC")
    if env_value:
        return int(env_value)
    return 600


def _run_cmd(cmd: list[str], step: str, timeout: int, cwd: Path, retries: int = 0) -> None:
    print(f"[RUN-ALL] step={step} cmd={' '.join(cmd)}")
    env = os.environ.copy()
    env["ETL_SUBPROCESS_TIMEOUT_SEC"] = str(timeout)
    attempt = 0
    while True:
        attempt += 1
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(cwd),
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            stdout_tail = _tail(exc.stdout)
            stderr_tail = _tail(exc.stderr)
            print(f"[ERROR] step={step} timeout after {timeout}s (attempt {attempt})")
            print("[ERROR] stdout tail:")
            print(stdout_tail)
            print("[ERROR] stderr tail:")
            print(stderr_tail)
            if retries > 0:
                retries -= 1
                print(f"[WARN] retrying step={step} after timeout")
                continue
            raise RuntimeError(f"{step} timed out") from exc

        if result.returncode != 0:
            print(f"[ERROR] step={step} rc={result.returncode}")
            print("[ERROR] stdout tail:")
            print(_tail(result.stdout))
            print("[ERROR] stderr tail:")
            print(_tail(result.stderr))
            raise RuntimeError(f"{step} failed with rc={result.returncode}")

        if result.stdout:
            print(_tail(result.stdout))
        return

def _tail(text: str | None, lines: int = 50) -> str:
    if not text:
        return ""
    parts = text.splitlines()
    return "\n".join(parts[-lines:])


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d")


def _select_asof_date(requested_date: datetime) -> Tuple[str, Path]:
    candidates = []
    for path in FEATURES_BASE.glob("*/*/*/features.parquet"):
        if not _is_canonical_features_path(path):
            continue
        date = _date_from_features_path(path)
        candidates.append((date, path))

    if not candidates:
        raise RuntimeError(f"No canonical features found under {FEATURES_BASE}")

    candidates.sort(key=lambda item: item[0])
    eligible = [item for item in candidates if item[0] <= requested_date]
    if not eligible:
        min_date = candidates[0][0].strftime("%Y-%m-%d")
        max_date = candidates[-1][0].strftime("%Y-%m-%d")
        raise RuntimeError(
            f"No canonical features <= {requested_date.strftime('%Y-%m-%d')}. "
            f"Available range: {min_date}..{max_date}"
        )

    asof_date, features_path = eligible[-1]
    return asof_date.strftime("%Y-%m-%d"), features_path


def _is_canonical_features_path(path: Path) -> bool:
    try:
        rel_parts = path.relative_to(FEATURES_BASE).parts
    except ValueError:
        return False
    return (
        len(rel_parts) == 4
        and rel_parts[3] == "features.parquet"
        and len(rel_parts[0]) == 4
        and rel_parts[0].isdigit()
        and len(rel_parts[1]) == 2
        and rel_parts[1].isdigit()
        and len(rel_parts[2]) == 2
        and rel_parts[2].isdigit()
    )


def _date_from_features_path(path: Path) -> datetime:
    parts = path.relative_to(FEATURES_BASE).parts
    return datetime.strptime(f"{parts[0]}-{parts[1]}-{parts[2]}", "%Y-%m-%d")


def _generate_final_decision(
    features_path: Path,
    asof_date: str,
    execution_date: str,
    execution_hour: str,
    top_k: int = 10,
) -> None:
    if not features_path.exists():
        raise RuntimeError(f"Features not found: {features_path}")

    import joblib

    intraday_model_path = _resolve_model_path(INTRADAY_MODEL_PATH, INTRADAY_MODEL_FALLBACK_PATH)
    intraday_model = joblib.load(intraday_model_path)
    current_df = pd.read_parquet(features_path)
    history_df = _load_decision_history(asof_date, DECISION_HISTORY_DAYS)
    oos_ticker_stats = _load_oos_ticker_stats()
    run_id = execution_date.replace("-", "") + "-" + execution_hour
    universe = (
        current_df["ticker"].astype(str).str.strip().str.upper().dropna().drop_duplicates().tolist()
        if "ticker" in current_df.columns
        else []
    )
    crypto_config = load_crypto_universe_config(CRYPTO_UNIVERSE_PATH) if CRYPTO_UNIVERSE_PATH.exists() else {}
    crypto_universe = list(crypto_config.get("symbols") or [])
    crypto_provider_health = _load_crypto_provider_health() if crypto_universe else {}
    engine_context = EngineContext(
        as_of=_parse_date(asof_date),
        run_id=run_id,
        mode="decision_generation",
        universe=universe,
        prices=current_df,
        config={
            "crypto_universe_path": str(CRYPTO_UNIVERSE_PATH) if CRYPTO_UNIVERSE_PATH.exists() else None,
            "crypto_universe": crypto_universe,
            "crypto_symbols": enabled_crypto_symbols(crypto_universe) if crypto_universe else [],
            "crypto_strategy": dict(crypto_config.get("strategy") or {}),
            "enable_crypto_market_data": _env_flag("ENABLE_CRYPTO_MARKET_DATA"),
        },
        provider_health=crypto_provider_health,
        metadata={
            "asof_date": asof_date,
            "execution_date": execution_date,
            "execution_hour": execution_hour,
            "features_path": str(features_path),
            "history_df": history_df,
            "top_k": top_k,
            "oos_ticker_stats": oos_ticker_stats,
            "crypto_provider_name": BinanceSpotMarketDataProvider.provider_name,
        },
    )

    intraday = _build_intraday_candidates(
        current_df=current_df,
        history_df=history_df,
        model=intraday_model,
        asof_date=asof_date,
        top_k=top_k,
        oos_ticker_stats=oos_ticker_stats,
    )
    long_term_engine = LongTermPortfolioEngine()
    long_term_result = long_term_engine.run(engine_context)
    _log_engine_result(long_term_result)
    long_term = list(long_term_result.diagnostics.metadata.get("decision_rows", []))

    crypto_engine = IntradayCryptoEngine()
    crypto_result = crypto_engine.run(engine_context)
    _log_engine_result(crypto_result)
    crypto_rows = list(crypto_result.diagnostics.metadata.get("decision_rows", []))
    if crypto_rows:
        intraday = intraday + crypto_rows

    payload = {
        "decision": {
            "intraday": intraday,
            "long_term": long_term,
        },
        "asof_date": asof_date,
        "execution_date": execution_date,
        "execution_hour": execution_hour,
        "features_path_used": str(features_path),
    }

    FINAL_DECISION_PATH.parent.mkdir(parents=True, exist_ok=True)
    FINAL_DECISION_PATH.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )


def _log_engine_result(result: Any) -> None:
    diagnostics = result.diagnostics
    print(
        f"[RUN-ALL] engine={result.engine_name} horizon={result.horizon} "
        f"seen={diagnostics.candidates_seen} scored={diagnostics.candidates_scored} "
        f"rejected={diagnostics.candidates_rejected}"
    )
    for warning in diagnostics.warnings:
        print(f"[RUN-ALL] engine={result.engine_name} warning={warning}")


def _env_flag(name: str) -> bool:
    value = str(os.getenv(name) or "").strip().lower()
    return value in {"1", "true", "yes", "y", "si", "s"}


def _load_crypto_provider_health() -> dict[str, dict[str, str]]:
    if not _env_flag("ENABLE_CRYPTO_MARKET_DATA"):
        return {}
    provider = BinanceSpotMarketDataProvider()
    health = provider.health_check()
    return {
        provider.provider_name: {
            "status": health.status,
            "message": health.message,
            "checked_at_utc": health.checked_at_utc,
        }
    }


def _resolve_model_path(primary: Path, fallback: Path | None = None) -> Path:
    if primary.exists():
        return primary
    if fallback and fallback.exists():
        return fallback
    raise RuntimeError(f"Model not found: {primary}" + (f" or {fallback}" if fallback else ""))


def _load_decision_history(asof_date: str, lookback_days: int) -> pd.DataFrame:
    end_date = _parse_date(asof_date)
    start_date = end_date - pd.Timedelta(days=lookback_days)
    frames: list[pd.DataFrame] = []
    for path in FEATURES_BASE.glob("*/*/*/features.parquet"):
        if not _is_canonical_features_path(path):
            continue
        date = _date_from_features_path(path)
        if start_date <= date < end_date:
            frames.append(pd.read_parquet(path))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _score_features(df: pd.DataFrame, model: Any, keep_latest_per_ticker: bool = False) -> pd.DataFrame:
    scored = df.copy()
    if "ticker" not in scored.columns:
        raise RuntimeError("features.parquet missing 'ticker' column")
    scored["ticker"] = scored["ticker"].astype(str).str.strip()
    scored = scored.dropna(subset=["ticker"])
    if keep_latest_per_ticker:
        sort_cols = ["ticker"]
        if "date" in scored.columns:
            sort_cols = ["ticker", "date"]
        scored = scored.sort_values(sort_cols).drop_duplicates(subset=["ticker"], keep="last")

    feature_names = None
    try:
        feature_names = model.get_booster().feature_names
    except Exception:
        feature_names = None

    if feature_names:
        X = scored.reindex(columns=feature_names)
    else:
        X = scored.select_dtypes(include=[np.number, "bool"])

    if hasattr(model, "predict_proba"):
        probs = model.predict_proba(X)
        scores = probs[:, 1] if getattr(probs, "ndim", 1) > 1 else probs
    else:
        scores = model.predict(X)
    scored["model_score"] = np.asarray(scores, dtype=float)
    return scored


def _build_intraday_candidates(
    current_df: pd.DataFrame,
    history_df: pd.DataFrame,
    model: Any,
    asof_date: str,
    top_k: int,
    oos_ticker_stats: dict[str, dict[str, float]] | None = None,
) -> list[dict[str, Any]]:
    current_scored = _score_features(current_df, model, keep_latest_per_ticker=True)
    history_scored = pd.DataFrame()
    if history_df is not None and not history_df.empty:
        history_scored = _score_features(history_df, model)

    stats = _empirical_ticker_stats(history_scored)
    global_mean = float(stats["global_mean_return"])
    rows: list[dict[str, Any]] = []

    for _, row in current_scored.iterrows():
        ticker = str(row["ticker"]).strip().upper()
        score = float(row.get("model_score") or 0.0)
        stat = stats["by_ticker"].get(ticker)
        if score < DECISION_MIN_SCORE or not stat:
            continue
        n_obs = int(stat["n"])
        hit_rate = float(stat["hit_rate"])
        mean_return = float(stat["mean_return"])
        oos_stat = (oos_ticker_stats or {}).get(ticker)
        if n_obs < DECISION_MIN_OBSERVATIONS:
            continue
        if hit_rate < DECISION_MIN_HIT_RATE:
            continue
        if oos_stat:
            if int(oos_stat.get("rows", 0)) < OOS_TICKER_MIN_TRADES:
                continue
            if float(oos_stat.get("hit_rate", 0.0)) < OOS_TICKER_MIN_HIT_RATE:
                continue
            if float(oos_stat.get("mean_ret_adj", 0.0)) < OOS_TICKER_MIN_MEAN_RET:
                continue
        blended_return = ((mean_return * n_obs) + (global_mean * DECISION_SHRINKAGE)) / (
            n_obs + DECISION_SHRINKAGE
        )
        if blended_return < DECISION_MIN_EXPECTED_RETURN:
            continue
        oos_multiplier = 1.0
        if oos_stat:
            oos_multiplier = min(
                1.5,
                max(
                    0.5,
                    (float(oos_stat.get("hit_rate", 0.0)) / OOS_TICKER_MIN_HIT_RATE)
                    * max(float(oos_stat.get("mean_ret_adj", 0.0)), OOS_TICKER_MIN_MEAN_RET)
                    / OOS_TICKER_MIN_MEAN_RET,
                ),
            )
        selection_score = score * blended_return * min(1.0, n_obs / 60.0) * oos_multiplier
        rows.append(
            {
                "ticker": ticker,
                "model_score": score,
                "expected_return_gross_pct": blended_return,
                "empirical_mean_return": mean_return,
                "empirical_hit_rate": hit_rate,
                "empirical_observations": n_obs,
                "oos_trade_mean_return": float(oos_stat.get("mean_ret_adj")) if oos_stat else None,
                "oos_trade_hit_rate": float(oos_stat.get("hit_rate")) if oos_stat else None,
                "oos_trade_count": int(oos_stat.get("rows")) if oos_stat else None,
                "selection_score": selection_score,
            }
        )

    rows.sort(key=lambda item: (-float(item["selection_score"]), -float(item["model_score"]), item["ticker"]))
    selected = rows[:top_k]
    total = sum(max(float(item["selection_score"]), 0.0) for item in selected)
    if total <= 0:
        return []

    intraday = []
    for item in selected:
        peso_pct = (max(float(item["selection_score"]), 0.0) / total) * 100.0
        intraday.append(
            {
                "ticker": item["ticker"],
                "peso_pct": round(peso_pct, 6),
                "model_score": round(float(item["model_score"]), 6),
                "expected_return_gross_pct": round(float(item["expected_return_gross_pct"]), 6),
                "selection_score": round(float(item["selection_score"]), 8),
                "empirical_mean_return": round(float(item["empirical_mean_return"]), 6),
                "empirical_hit_rate": round(float(item["empirical_hit_rate"]), 6),
                "empirical_observations": int(item["empirical_observations"]),
                "oos_trade_mean_return": round(float(item["oos_trade_mean_return"]), 6)
                if item.get("oos_trade_mean_return") is not None
                else None,
                "oos_trade_hit_rate": round(float(item["oos_trade_hit_rate"]), 6)
                if item.get("oos_trade_hit_rate") is not None
                else None,
                "oos_trade_count": int(item["oos_trade_count"]) if item.get("oos_trade_count") is not None else None,
                "justificacion": (
                    f"model_score={float(item['model_score']):.6f} day={asof_date} "
                    f"| empirical_mean={float(item['empirical_mean_return']):.6f} "
                    f"| empirical_hit={float(item['empirical_hit_rate']):.6f} "
                    f"| empirical_n={int(item['empirical_observations'])}"
                    + (
                        f" | oos_trade_mean={float(item['oos_trade_mean_return']):.6f}"
                        f" | oos_trade_hit={float(item['oos_trade_hit_rate']):.6f}"
                        f" | oos_trade_n={int(item['oos_trade_count'])}"
                        if item.get("oos_trade_mean_return") is not None
                        else ""
                    )
                ),
            }
        )
    return intraday


def _load_oos_ticker_stats() -> dict[str, dict[str, float]]:
    if not OOS_TICKER_SUMMARY_PATH.exists():
        return {}
    try:
        payload = json.loads(OOS_TICKER_SUMMARY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, list):
        return {}
    stats: dict[str, dict[str, float]] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        stats[ticker] = {
            "rows": float(item.get("rows") or 0.0),
            "mean_ret_adj": float(item.get("mean_ret_adj") or 0.0),
            "hit_rate": float(item.get("hit_rate") or 0.0),
        }
    return stats


def _empirical_ticker_stats(history_scored: pd.DataFrame) -> dict[str, Any]:
    if history_scored is None or history_scored.empty:
        return {"global_mean_return": 0.0, "by_ticker": {}}
    if "target_regresion_t+1" not in history_scored.columns:
        return {"global_mean_return": 0.0, "by_ticker": {}}

    df = history_scored.copy()
    df = df.dropna(subset=["ticker", "target_regresion_t+1", "model_score"])
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    df = df[df["model_score"] >= DECISION_MIN_SCORE]
    if df.empty:
        return {"global_mean_return": 0.0, "by_ticker": {}}

    grouped = df.groupby("ticker").agg(
        n=("ticker", "size"),
        mean_return=("target_regresion_t+1", "mean"),
        hit_rate=("target_regresion_t+1", lambda s: float((s > 0).mean())),
    )
    by_ticker = grouped.to_dict(orient="index")
    global_mean = float(df["target_regresion_t+1"].mean())
    return {"global_mean_return": global_mean, "by_ticker": by_ticker}


def _build_long_term_candidates(
    current_df: pd.DataFrame,
    history_df: pd.DataFrame,
    asof_date: str,
    top_k: int,
) -> list[dict[str, Any]]:
    if not LONG_TERM_MODEL_PATH.exists():
        return []

    import joblib

    model = joblib.load(LONG_TERM_MODEL_PATH)
    current_scored = _predict_regression(current_df, model, "predicted_return", keep_latest_per_ticker=True)
    history_scored = pd.DataFrame()
    if history_df is not None and not history_df.empty:
        history_scored = _predict_regression(history_df, model, "predicted_return")

    stats = _long_term_empirical_stats(history_scored)
    global_mean = float(stats["global_mean_return"])
    rows: list[dict[str, Any]] = []

    for _, row in current_scored.iterrows():
        ticker = str(row["ticker"]).strip().upper()
        predicted_return = float(row.get("predicted_return") or 0.0)
        stat = stats["by_ticker"].get(ticker)
        if predicted_return < LONG_TERM_MIN_PREDICTED_RETURN or not stat:
            continue
        n_obs = int(stat["n"])
        hit_rate = float(stat["hit_rate"])
        mean_return = float(stat["mean_return"])
        if n_obs < LONG_TERM_MIN_OBSERVATIONS:
            continue
        if hit_rate < LONG_TERM_MIN_HIT_RATE:
            continue
        blended_return = ((mean_return * n_obs) + (global_mean * LONG_TERM_SHRINKAGE)) / (
            n_obs + LONG_TERM_SHRINKAGE
        )
        if blended_return < LONG_TERM_MIN_EXPECTED_RETURN:
            continue
        selection_score = predicted_return * blended_return * min(1.0, n_obs / 60.0)
        rows.append(
            {
                "ticker": ticker,
                "predicted_return": predicted_return,
                "expected_return_gross_pct": blended_return,
                "empirical_mean_return": mean_return,
                "empirical_hit_rate": hit_rate,
                "empirical_observations": n_obs,
                "selection_score": selection_score,
            }
        )

    rows.sort(key=lambda item: (-float(item["selection_score"]), -float(item["predicted_return"]), item["ticker"]))
    selected = rows[:top_k]
    total = sum(max(float(item["selection_score"]), 0.0) for item in selected)
    if total <= 0:
        return []

    long_term = []
    for item in selected:
        peso_pct = (max(float(item["selection_score"]), 0.0) / total) * 100.0
        long_term.append(
            {
                "ticker": item["ticker"],
                "peso_pct": round(peso_pct, 6),
                "model_score": round(float(item["predicted_return"]), 6),
                "expected_return_gross_pct": round(float(item["expected_return_gross_pct"]), 6),
                "selection_score": round(float(item["selection_score"]), 8),
                "empirical_mean_return": round(float(item["empirical_mean_return"]), 6),
                "empirical_hit_rate": round(float(item["empirical_hit_rate"]), 6),
                "empirical_observations": int(item["empirical_observations"]),
                "justificacion": (
                    f"predicted_return={float(item['predicted_return']):.6f} day={asof_date} "
                    f"| empirical_mean={float(item['empirical_mean_return']):.6f} "
                    f"| empirical_hit={float(item['empirical_hit_rate']):.6f} "
                    f"| empirical_n={int(item['empirical_observations'])}"
                ),
            }
        )
    return long_term


def _predict_regression(
    df: pd.DataFrame,
    model: Any,
    output_col: str,
    keep_latest_per_ticker: bool = False,
) -> pd.DataFrame:
    scored = df.copy()
    if "ticker" not in scored.columns:
        raise RuntimeError("features.parquet missing 'ticker' column")
    scored["ticker"] = scored["ticker"].astype(str).str.strip()
    scored = scored.dropna(subset=["ticker"])
    if keep_latest_per_ticker:
        sort_cols = ["ticker"]
        if "date" in scored.columns:
            sort_cols = ["ticker", "date"]
        scored = scored.sort_values(sort_cols).drop_duplicates(subset=["ticker"], keep="last")

    feature_names = None
    try:
        feature_names = model.get_booster().feature_names
    except Exception:
        feature_names = None

    if feature_names:
        X = scored.reindex(columns=feature_names)
    else:
        X = scored.select_dtypes(include=[np.number, "bool"])
    scored[output_col] = np.asarray(model.predict(X), dtype=float)
    return scored


def _long_term_empirical_stats(history_scored: pd.DataFrame) -> dict[str, Any]:
    if history_scored is None or history_scored.empty:
        return {"global_mean_return": 0.0, "by_ticker": {}}
    if "target_regresion_t+5" not in history_scored.columns:
        return {"global_mean_return": 0.0, "by_ticker": {}}

    df = history_scored.copy()
    df = df.dropna(subset=["ticker", "target_regresion_t+5", "predicted_return"])
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    df = df[df["predicted_return"] >= LONG_TERM_MIN_PREDICTED_RETURN]
    if df.empty:
        return {"global_mean_return": 0.0, "by_ticker": {}}

    grouped = df.groupby("ticker").agg(
        n=("ticker", "size"),
        mean_return=("target_regresion_t+5", "mean"),
        hit_rate=("target_regresion_t+5", lambda s: float((s > 0).mean())),
    )
    by_ticker = grouped.to_dict(orient="index")
    global_mean = float(df["target_regresion_t+5"].mean())
    return {"global_mean_return": global_mean, "by_ticker": by_ticker}


def _validate_required_outputs(
    run_id: str,
    asof_date: str,
    emit_recommendations: bool,
    skip_backtest: bool,
    skip_simulate: bool,
) -> None:
    processed_daily = ROOT / "data" / "processed_daily"
    if not list(processed_daily.glob("*_daily.parquet")):
        raise RuntimeError("Missing processed_daily outputs. Run orchestrator or check inputs.")

    features_path = FEATURES_BASE / asof_date.replace("-", "/") / "features.parquet"
    if not features_path.exists():
        raise RuntimeError(f"Missing features for asof_date: {features_path}")

    if not skip_backtest and not BACKTEST_SUMMARY_PATH.exists():
        raise RuntimeError(f"Missing backtest summary: {BACKTEST_SUMMARY_PATH}")

    if not skip_simulate and not SIMULATE_SUMMARY_PATH.exists():
        raise RuntimeError(f"Missing simulate summary: {SIMULATE_SUMMARY_PATH}")

    if not FINAL_DECISION_PATH.exists():
        raise RuntimeError(f"Missing final decision: {FINAL_DECISION_PATH}")


def _validate_run_outputs(run_id: str, emit_recommendations: bool) -> None:
    run_root = ROOT / "runs" / run_id
    manifest = run_root / "manifests" / f"run_manifest.v{CURRENT_SCHEMA_VERSION}.json"
    if not manifest.exists():
        raise RuntimeError(f"Missing manifest: {manifest}")
    if not list(run_root.glob("artifacts/decision.outputs.v*.json")):
        raise RuntimeError("Missing decision.outputs artifact")
    if not list(run_root.glob("artifacts/evaluation.metrics.v*.json")):
        raise RuntimeError("Missing evaluation.metrics artifact")
    if emit_recommendations and not list(run_root.glob("artifacts/recommendation.outputs.v*.json")):
        raise RuntimeError("Missing recommendation.outputs artifact")
    if emit_recommendations and not list(run_root.glob("artifacts/execution.plan.v*.json")):
        raise RuntimeError("Missing execution.plan artifact")


def _print_dry_run(
    commands: list[str],
    requested_date: datetime,
    skip_backtest: bool,
    skip_simulate: bool,
    timeout: int,
) -> None:
    print("[RUN-ALL] DRY RUN")
    print(f"- requested_date={requested_date.strftime('%Y-%m-%d')}")
    print(f"- orchestrator_cmd={' '.join(commands)}")
    print(f"- ETL_SUBPROCESS_TIMEOUT_SEC={timeout}")
    if not skip_backtest:
        print("- backtest_cmd: python -m src.backtest.backtest_strategy --date <asof_date> --lookback-days 252")
    if not skip_simulate:
        print("- simulate_cmd: python -m src.simulations.simulate_estrategy --date <asof_date> --lookback-days 252")
    print("- final_decision: data/results/final_decision.json")
    print("- adapter: build_decision_intel_artifacts(...)")
