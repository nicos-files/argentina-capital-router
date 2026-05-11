from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


STRATEGY_FIELDS = [
    "name",
    "timeframe",
    "lookback_limit",
    "fast_ma_window",
    "slow_ma_window",
    "min_abs_signal_strength",
    "max_volatility_pct",
    "risk_reward_ratio",
    "stop_loss_pct",
    "take_profit_pct",
    "max_paper_notional",
    "allow_short",
]

INFO_MESSAGES = [
    "Paper-only proposal; no real execution occurred.",
    "This proposal did not modify production crypto.json.",
    "Winning config was not auto-applied.",
]


def load_crypto_promotion_inputs(
    *,
    experiment_dir: str | Path,
    current_config_path: str | Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    base = Path(experiment_dir)
    results_path = base / "crypto_paper_experiment_results.json"
    rankings_path = base / "crypto_paper_experiment_rankings.json"
    config_path = Path(current_config_path)
    if not results_path.exists():
        raise FileNotFoundError(f"Missing experiment results file: {results_path}")
    if not rankings_path.exists():
        raise FileNotFoundError(f"Missing experiment rankings file: {rankings_path}")
    if not config_path.exists():
        raise FileNotFoundError(f"Missing current crypto config file: {config_path}")
    results_payload = json.loads(results_path.read_text(encoding="utf-8"))
    rankings = json.loads(rankings_path.read_text(encoding="utf-8"))
    current_config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(results_payload, dict):
        raise ValueError("Experiment results payload must be a JSON object.")
    if not isinstance(rankings, list):
        raise ValueError("Experiment rankings payload must be a JSON array.")
    if not isinstance(current_config, dict):
        raise ValueError("Current crypto config must be a JSON object.")
    return results_payload, rankings, current_config


def select_crypto_experiment_config(
    *,
    results_payload: dict[str, Any],
    rankings: list[dict[str, Any]],
    config_id: str | None = None,
    use_best_eligible: bool = False,
) -> tuple[dict[str, Any], str]:
    if not config_id and not use_best_eligible:
        raise ValueError("Either config_id or use_best_eligible must be provided.")
    results = list(results_payload.get("results") or [])
    if config_id:
        for item in results:
            if str(item.get("config_id")) == str(config_id):
                return dict(item), "config_id"
        raise ValueError(f"Selected config_id not found in experiment results: {config_id}")
    for item in rankings:
        if bool(item.get("eligible")):
            selected_id = str(item.get("config_id"))
            for result in results:
                if str(result.get("config_id")) == selected_id:
                    return dict(result), "best_eligible"
    raise ValueError("No eligible config found in experiment rankings.")


def build_crypto_config_candidate(
    *,
    current_config: dict[str, Any],
    selected_result: dict[str, Any],
    paper_forward_enable: bool = False,
) -> dict[str, Any]:
    candidate = deepcopy(current_config)
    strategy = dict(candidate.get("strategy") or {})
    selected_config = dict(selected_result.get("config") or {})
    strategy["name"] = str(selected_config.get("name") or strategy.get("name") or "intraday_crypto_baseline")
    for field in STRATEGY_FIELDS:
        if field == "name":
            continue
        if field in selected_config:
            strategy[field] = selected_config[field]
    strategy["allow_short"] = False
    strategy["enabled"] = bool(paper_forward_enable) if paper_forward_enable else bool(strategy.get("enabled", False))
    if not paper_forward_enable:
        strategy["enabled"] = False
    candidate["strategy"] = strategy

    selected_symbols = {str(symbol).upper() for symbol in (selected_result.get("symbols") or [])}
    symbols = []
    for item in list(candidate.get("symbols") or []):
        symbol_item = dict(item or {})
        symbol = str(symbol_item.get("symbol") or "").upper()
        symbol_item["live_enabled"] = False
        symbol_item["paper_enabled"] = bool(symbol_item.get("paper_enabled", True))
        symbol_item["strategy_enabled"] = bool(paper_forward_enable and symbol in selected_symbols)
        symbols.append(symbol_item)
    candidate["symbols"] = symbols
    return candidate


def build_crypto_config_diff(
    current_config: dict[str, Any],
    candidate_config: dict[str, Any],
) -> dict[str, Any]:
    changed_fields: list[dict[str, Any]] = []
    added_fields: list[dict[str, Any]] = []
    removed_fields: list[dict[str, Any]] = []
    _walk_diff("", current_config, candidate_config, changed_fields, added_fields, removed_fields)
    return {
        "changed_fields": changed_fields,
        "added_fields": added_fields,
        "removed_fields": removed_fields,
        "safety_assertions": {
            "live_enabled_all_symbols": any(bool((item or {}).get("live_enabled")) for item in list(candidate_config.get("symbols") or [])),
            "api_keys_present": _has_sensitive_keys(candidate_config, {"api_key", "apikey", "secret", "token"}),
            "broker_settings_present": _has_sensitive_keys(candidate_config, {"broker", "broker_settings", "broker_api"}),
            "non_crypto_sections_modified": any(not str(change.get("path", "")).startswith(("strategy", "symbols")) for change in changed_fields + added_fields + removed_fields),
        },
    }


def validate_crypto_config_promotion(
    *,
    current_config: dict[str, Any],
    candidate_config: dict[str, Any],
    selected_result: dict[str, Any],
    diff_payload: dict[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    info: list[str] = list(INFO_MESSAGES)
    strategy = dict(candidate_config.get("strategy") or {})
    metrics = dict(selected_result.get("metrics") or {})
    required_fields = [
        "timeframe",
        "fast_ma_window",
        "slow_ma_window",
        "min_abs_signal_strength",
        "max_volatility_pct",
        "stop_loss_pct",
        "take_profit_pct",
        "max_paper_notional",
    ]
    for field in required_fields:
        if field not in strategy:
            errors.append(f"missing_strategy_field:{field}")
    fast = int(strategy.get("fast_ma_window") or 0)
    slow = int(strategy.get("slow_ma_window") or 0)
    if fast <= 0 or slow <= 0 or fast >= slow:
        errors.append("fast_ma_window_must_be_less_than_slow_ma_window")
    if float(strategy.get("stop_loss_pct") or 0.0) <= 0.0:
        errors.append("stop_loss_pct_must_be_positive")
    if float(strategy.get("take_profit_pct") or 0.0) <= 0.0:
        errors.append("take_profit_pct_must_be_positive")
    if float(strategy.get("max_paper_notional") or 0.0) <= 0.0:
        errors.append("max_paper_notional_must_be_positive")
    if diff_payload["safety_assertions"]["live_enabled_all_symbols"]:
        errors.append("candidate_must_keep_live_enabled_false")
    if diff_payload["safety_assertions"]["api_keys_present"]:
        errors.append("candidate_must_not_add_api_keys")
    if diff_payload["safety_assertions"]["broker_settings_present"]:
        errors.append("candidate_must_not_add_broker_settings")
    if diff_payload["safety_assertions"]["non_crypto_sections_modified"]:
        errors.append("candidate_must_not_modify_non_crypto_sections")

    closed_trades = int(selected_result.get("closed_trades_count") or metrics.get("closed_trades_count") or 0)
    expectancy = _safe_float(selected_result.get("expectancy", metrics.get("expectancy")))
    profit_factor = _safe_float(selected_result.get("profit_factor", metrics.get("profit_factor")))
    max_drawdown_pct = _safe_float(selected_result.get("max_drawdown_pct", metrics.get("max_drawdown_pct")))
    if closed_trades < 5:
        warnings.append("closed_trades_count below preferred threshold.")
    if closed_trades < 30:
        warnings.append("Small sample size: fewer than 30 closed trades.")
    if expectancy is None or expectancy <= 0.0:
        warnings.append("Non-positive expectancy in selected config.")
    if profit_factor is None or profit_factor <= 1.0:
        warnings.append("Profit factor is not above 1.0.")
    if max_drawdown_pct is not None and max_drawdown_pct < -20.0:
        warnings.append("Max drawdown is worse than preferred threshold.")
    if _safe_float(selected_result.get("total_fees")) is None or _safe_float(selected_result.get("total_slippage")) is None:
        warnings.append("Fee/slippage assumptions missing from experiment result.")
    if any("Drawdown calculated" in str(item) for item in list(selected_result.get("warnings") or [])):
        warnings.append("Drawdown was calculated from event-level equity points.")
    warnings.append("Strategy is not proven live.")

    return {
        "eligible_for_candidate": not errors,
        "errors": _dedupe(errors),
        "warnings": _dedupe(warnings),
        "info": _dedupe(info),
        "paper_only": True,
        "live_trading": False,
        "metrics_snapshot": {
            "closed_trades_count": closed_trades,
            "open_trades_count": int(selected_result.get("open_trades_count") or metrics.get("open_trades_count") or 0),
            "net_profit": _safe_float(selected_result.get("net_profit", metrics.get("net_profit"))),
            "expectancy": expectancy,
            "profit_factor": profit_factor,
            "win_rate": _safe_float(selected_result.get("win_rate", metrics.get("win_rate"))),
            "max_drawdown_pct": max_drawdown_pct,
            "total_fees": _safe_float(selected_result.get("total_fees", metrics.get("total_fees"))),
            "total_slippage": _safe_float(selected_result.get("total_slippage", metrics.get("total_slippage"))),
        },
        "safety_assertions": diff_payload.get("safety_assertions", {}),
    }


def build_crypto_config_promotion_report(
    *,
    experiment_name: str,
    selected_result: dict[str, Any],
    selection_method: str,
    candidate_config: dict[str, Any],
    current_config: dict[str, Any],
    diff_payload: dict[str, Any],
    validation_payload: dict[str, Any],
    paper_forward_enable: bool,
) -> str:
    current_strategy = dict(current_config.get("strategy") or {})
    candidate_strategy = dict(candidate_config.get("strategy") or {})
    metrics = dict(validation_payload.get("metrics_snapshot") or {})
    lines = [
        "# Crypto Config Promotion Proposal",
        "",
        "## Summary",
        f"- Experiment name: {experiment_name}",
        f"- Selected config ID: {selected_result.get('config_id')}",
        f"- Selection method: {selection_method}",
        f"- Eligible for candidate: {validation_payload.get('eligible_for_candidate')}",
        f"- Paper-forward enabled: {'yes' if paper_forward_enable else 'no'}",
        "- Live trading enabled: no",
        "",
        "## Selected Metrics",
        f"- Closed trades: {metrics.get('closed_trades_count')}",
        f"- Open trades: {metrics.get('open_trades_count')}",
        f"- Net profit: {metrics.get('net_profit')}",
        f"- Expectancy: {metrics.get('expectancy')}",
        f"- Profit factor: {metrics.get('profit_factor')}",
        f"- Win rate: {metrics.get('win_rate')}",
        f"- Max drawdown: {metrics.get('max_drawdown_pct')}",
        f"- Total fees: {metrics.get('total_fees')}",
        f"- Total slippage: {metrics.get('total_slippage')}",
        "",
        "## Proposed Strategy Parameters",
        "| Parameter | Current value | Candidate value |",
        "| --- | --- | --- |",
    ]
    for field in STRATEGY_FIELDS:
        lines.append(f"| {field} | {current_strategy.get(field)} | {candidate_strategy.get(field)} |")
    lines.extend(
        [
            "",
            "## Safety Checks",
            f"- live_enabled remains false: {not diff_payload['safety_assertions'].get('live_enabled_all_symbols')}",
            f"- no API keys: {not diff_payload['safety_assertions'].get('api_keys_present')}",
            f"- no broker settings: {not diff_payload['safety_assertions'].get('broker_settings_present')}",
            "- no live trading: true",
            "- paper-only candidate: true",
            "",
            "## Validation Errors",
        ]
    )
    if validation_payload["errors"]:
        for item in validation_payload["errors"]:
            lines.append(f"- {item}")
    else:
        lines.append("- None.")
    lines.extend(["", "## Validation Warnings"])
    if validation_payload["warnings"]:
        for item in validation_payload["warnings"]:
            lines.append(f"- {item}")
    else:
        lines.append("- None.")
    lines.extend(
        [
            "",
            "## Manual Review Instructions",
            "- This did not modify production crypto.json.",
            "- Review crypto_config_candidate.json.",
            "- If accepted, manually copy or apply changes.",
            "- Run paper-forward testing before any live integration.",
            "- Do not enable live trading.",
            "",
            "## Notes",
            "- Paper-only.",
            "- Simulated fees and slippage.",
            "- No real orders placed.",
            "- Winning config was not auto-applied.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_crypto_config_promotion_artifacts(
    *,
    output_dir: str | Path,
    candidate_config: dict[str, Any],
    diff_payload: dict[str, Any],
    validation_payload: dict[str, Any],
    report_text: str,
) -> dict[str, Path]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    payloads = {
        "crypto_config_candidate.json": candidate_config,
        "crypto_config_diff.json": diff_payload,
        "crypto_config_promotion_validation.json": validation_payload,
    }
    written: dict[str, Path] = {}
    for filename, payload in payloads.items():
        path = root / filename
        path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
        written[filename] = path
    report_path = root / "crypto_config_promotion_proposal.md"
    report_path.write_text(report_text, encoding="utf-8")
    written[report_path.name] = report_path
    return written


def create_crypto_config_promotion_proposal(
    *,
    experiment_dir: str | Path,
    current_config_path: str | Path,
    output_dir: str | Path,
    config_id: str | None = None,
    use_best_eligible: bool = False,
    paper_forward_enable: bool = False,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str, dict[str, Path]]:
    results_payload, rankings, current_config = load_crypto_promotion_inputs(
        experiment_dir=experiment_dir,
        current_config_path=current_config_path,
    )
    selected_result, selection_method = select_crypto_experiment_config(
        results_payload=results_payload,
        rankings=rankings,
        config_id=config_id,
        use_best_eligible=use_best_eligible,
    )
    candidate_config = build_crypto_config_candidate(
        current_config=current_config,
        selected_result=selected_result,
        paper_forward_enable=paper_forward_enable,
    )
    diff_payload = build_crypto_config_diff(current_config, candidate_config)
    validation_payload = validate_crypto_config_promotion(
        current_config=current_config,
        candidate_config=candidate_config,
        selected_result=selected_result,
        diff_payload=diff_payload,
    )
    report_text = build_crypto_config_promotion_report(
        experiment_name=str(((results_payload.get("summary") or {}).get("experiment_name")) or Path(experiment_dir).name),
        selected_result=selected_result,
        selection_method=selection_method,
        candidate_config=candidate_config,
        current_config=current_config,
        diff_payload=diff_payload,
        validation_payload=validation_payload,
        paper_forward_enable=paper_forward_enable,
    )
    written = write_crypto_config_promotion_artifacts(
        output_dir=output_dir,
        candidate_config=candidate_config,
        diff_payload=diff_payload,
        validation_payload=validation_payload,
        report_text=report_text,
    )
    return candidate_config, diff_payload, validation_payload, report_text, written


def _walk_diff(
    prefix: str,
    old: Any,
    new: Any,
    changed_fields: list[dict[str, Any]],
    added_fields: list[dict[str, Any]],
    removed_fields: list[dict[str, Any]],
) -> None:
    if isinstance(old, dict) and isinstance(new, dict):
        old_keys = set(old.keys())
        new_keys = set(new.keys())
        for key in sorted(old_keys & new_keys):
            path = f"{prefix}.{key}" if prefix else str(key)
            _walk_diff(path, old[key], new[key], changed_fields, added_fields, removed_fields)
        for key in sorted(new_keys - old_keys):
            path = f"{prefix}.{key}" if prefix else str(key)
            added_fields.append({"path": path, "new": new[key]})
        for key in sorted(old_keys - new_keys):
            path = f"{prefix}.{key}" if prefix else str(key)
            removed_fields.append({"path": path, "old": old[key]})
        return
    if isinstance(old, list) and isinstance(new, list):
        if old != new:
            changed_fields.append({"path": prefix, "old": old, "new": new})
        return
    if old != new:
        changed_fields.append({"path": prefix, "old": old, "new": new})


def _has_sensitive_keys(payload: Any, names: set[str]) -> bool:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if str(key).lower() in names:
                return True
            if _has_sensitive_keys(value, names):
                return True
    elif isinstance(payload, list):
        for item in payload:
            if _has_sensitive_keys(item, names):
                return True
    return False


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item)
        if text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
