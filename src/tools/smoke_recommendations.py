from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from src.decision_intel.contracts.metadata_models import CURRENT_SCHEMA_VERSION
from src.decision_intel.policies.topk_net_after_fees import CAPITAL_USD, MAX_WEIGHT


def main() -> int:
    date = "2026-01-19"
    hour = "1519"
    if len(sys.argv) >= 2:
        date = sys.argv[1]
    if len(sys.argv) >= 3:
        hour = sys.argv[2]

    cmd = [
        sys.executable,
        "-m",
        "src.cli",
        "run-all",
        "--mode",
        "offline",
        "--date",
        date,
        "--hour",
        hour,
        "--timeout-sec",
        "900",
        "--emit-recommendations",
    ]
    result = subprocess.run(cmd, text=True, capture_output=True)
    if result.returncode != 0:
        print("[SMOKE] run-all failed")
        print(result.stdout)
        print(result.stderr)
        return result.returncode

    run_id = date.replace("-", "") + "-" + hour
    run_root = Path("runs") / run_id
    rec_path = run_root / "artifacts" / f"recommendation.outputs.v{CURRENT_SCHEMA_VERSION}.json"
    csv_path = run_root / "artifacts" / "exports" / "recommendation.outputs.csv"
    plan_path = run_root / "artifacts" / f"execution.plan.v{CURRENT_SCHEMA_VERSION}.json"
    plan_csv_path = run_root / "artifacts" / "exports" / "execution.plan.csv"
    if not rec_path.exists():
        print(f"[SMOKE] missing recommendations: {rec_path}")
        return 2
    if not csv_path.exists():
        print(f"[SMOKE] missing recommendation export: {csv_path}")
        return 3
    if not plan_path.exists():
        print(f"[SMOKE] missing execution plan: {plan_path}")
        return 10
    if not plan_csv_path.exists():
        print(f"[SMOKE] missing execution plan export: {plan_csv_path}")
        return 11

    payload = json.loads(rec_path.read_text(encoding="utf-8"))
    items = payload.get("recommendations", [])
    cash_summary = payload.get("cash_summary", {})
    horizons = {item.get("horizon") for item in items if item.get("horizon")}
    for horizon in horizons:
        buy_items = [item for item in items if item.get("horizon") == horizon and item.get("action") == "BUY"]
        weight_sum = sum(float(item.get("weight") or 0.0) for item in buy_items)
        if buy_items and weight_sum - 1.0 > 1e-6:
            print(f"[SMOKE] weight sum exceeds 1.0 for {horizon}: {weight_sum}")
            return 4
        cash_info = cash_summary.get(horizon, {}) if isinstance(cash_summary, dict) else {}
        cash_retained = cash_info.get("cash_retained_usd")
        cap = MAX_WEIGHT.get(horizon, 1.0)
        for item in buy_items:
            constraints = item.get("constraints")
            constraints = constraints if isinstance(constraints, list) else []
            if float(item.get("weight") or 0.0) > cap + 1e-9:
                if "cap_relaxed_single_buy" not in constraints:
                    print(f"[SMOKE] cap violation for {horizon}: {item}")
                    return 5
            if float(item.get("qty_target") or 0.0) < 0:
                print(f"[SMOKE] negative qty_target for {horizon}: {item}")
                return 6
            if not item.get("broker_selected"):
                print(f"[SMOKE] missing broker_selected for {horizon}: {item}")
                return 7
            if item.get("currency") not in {"USD", "ARS"}:
                print(f"[SMOKE] invalid currency for {horizon}: {item}")
                return 8
            if item.get("order_side") != "BUY":
                print(f"[SMOKE] missing order_side for BUY item {horizon}: {item}")
                return 12
            if item.get("order_type") != "MARKET":
                print(f"[SMOKE] invalid order_type for {horizon}: {item}")
                return 13
            if item.get("time_in_force") != "DAY":
                print(f"[SMOKE] invalid time_in_force for {horizon}: {item}")
                return 14
            if item.get("currency") != "USD" and item.get("fx_rate_used") is None:
                if item.get("order_status") != "BLOCKED_FX":
                    print(f"[SMOKE] missing FX block for {horizon}: {item}")
                    return 15
            allow_fractional = bool(item.get("allow_fractional"))
            lot_size = float(item.get("lot_size") or 1.0)
            qty = float(item.get("qty_target") or 0.0)
            if not allow_fractional and lot_size > 0:
                remainder = abs(qty / lot_size - round(qty / lot_size))
                if remainder > 1e-9:
                    print(f"[SMOKE] lot_size violation for {horizon}: {item}")
                    return 9
        if buy_items and cash_retained is not None:
            total_usd = sum(float(item.get("usd_target_effective") or 0.0) for item in buy_items)
            expected_retained = max(CAPITAL_USD.get(horizon, 0.0) - total_usd, 0.0)
            if abs(float(cash_retained) - expected_retained) > 1e-6:
                print(f"[SMOKE] cash retention mismatch for {horizon}: {cash_retained} vs {expected_retained}")
                return 16

    plan_payload = json.loads(plan_path.read_text(encoding="utf-8"))
    orders = plan_payload.get("orders", [])
    for order in orders:
        if order.get("order_status") not in {"READY", "CLIPPED_CASH"}:
            print(f"[SMOKE] invalid execution plan status: {order}")
            return 17
        if float(order.get("order_qty") or 0.0) <= 0:
            print(f"[SMOKE] invalid execution plan qty: {order}")
            return 18
        if not order.get("broker_selected"):
            print(f"[SMOKE] missing broker in execution plan: {order}")
            return 19

    print("[SMOKE] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
