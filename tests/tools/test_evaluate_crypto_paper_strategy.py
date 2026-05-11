import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.execution.crypto_paper_models import CryptoPaperExitEvent, CryptoPaperFill, CryptoPaperPortfolioSnapshot
from src.tools.evaluate_crypto_paper_strategy import run_evaluate_crypto_paper_strategy


class EvaluateCryptoPaperStrategyToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.prev_flag = os.getenv("ENABLE_CRYPTO_PAPER_EVALUATION")

    def tearDown(self) -> None:
        if self.prev_flag is None:
            os.environ.pop("ENABLE_CRYPTO_PAPER_EVALUATION", None)
        else:
            os.environ["ENABLE_CRYPTO_PAPER_EVALUATION"] = self.prev_flag

    def _fill(
        self,
        fill_id: str,
        side: str,
        *,
        symbol: str = "BTCUSDT",
        quantity: float = 0.1,
        fill_price: float = 100.0,
        filled_at: datetime | None = None,
        fee: float = 0.1,
        slippage: float = 0.05,
        metadata: dict | None = None,
    ) -> CryptoPaperFill:
        when = filled_at or datetime(2026, 4, 25, 10, 0, 0)
        gross_notional = quantity * fill_price
        return CryptoPaperFill(
            fill_id=fill_id,
            order_id=f"order-{fill_id}",
            symbol=symbol,
            side=side,
            quantity=quantity,
            fill_price=fill_price,
            gross_notional=gross_notional,
            fee=fee,
            slippage=slippage,
            net_notional=(gross_notional + fee) if side == "BUY" else (gross_notional - fee),
            filled_at=when,
            metadata=metadata or {},
        )

    def _write_artifacts(self, artifact_root: Path) -> None:
        artifact_root.mkdir(parents=True, exist_ok=True)
        buy = self._fill("b1", "BUY", filled_at=datetime(2026, 4, 25, 10, 0, 0))
        sell = self._fill(
            "s1",
            "SELL",
            fill_price=110.0,
            filled_at=datetime(2026, 4, 25, 11, 0, 0),
            metadata={"exit_reason": "TAKE_PROFIT"},
        )
        exit_event = CryptoPaperExitEvent(
            exit_id="e1",
            symbol="BTCUSDT",
            position_quantity_before=0.1,
            exit_quantity=0.1,
            exit_reason="TAKE_PROFIT",
            trigger_price=110.0,
            fill_price=110.0,
            gross_notional=11.0,
            fee=0.1,
            slippage=0.05,
            realized_pnl=0.8,
            exited_at=datetime(2026, 4, 25, 11, 0, 0),
            source="unit",
        )
        snapshot = CryptoPaperPortfolioSnapshot(
            as_of=datetime(2026, 4, 25, 12, 0, 0),
            cash=100.8,
            equity=100.8,
            positions_value=0.0,
            realized_pnl=0.8,
            unrealized_pnl=0.0,
            fees_paid=0.2,
            positions=[],
        )
        (artifact_root / "crypto_paper_fills.json").write_text(
            json.dumps([buy.to_dict(), sell.to_dict()], ensure_ascii=False),
            encoding="utf-8",
        )
        (artifact_root / "crypto_paper_exit_events.json").write_text(
            json.dumps([exit_event.to_dict()], ensure_ascii=False),
            encoding="utf-8",
        )
        (artifact_root / "crypto_paper_orders.json").write_text("[]", encoding="utf-8")
        (artifact_root / "crypto_paper_snapshot.json").write_text(
            json.dumps(snapshot.to_dict(), ensure_ascii=False),
            encoding="utf-8",
        )

    def test_without_flag_refuses_safely(self) -> None:
        os.environ.pop("ENABLE_CRYPTO_PAPER_EVALUATION", None)
        with tempfile.TemporaryDirectory() as tmp:
            result = run_evaluate_crypto_paper_strategy(run_id="20260425-1900", base_path=tmp)
            self.assertEqual(result["status"], "SKIPPED")

    def test_with_flag_and_sample_artifacts_writes_evaluation_outputs(self) -> None:
        os.environ["ENABLE_CRYPTO_PAPER_EVALUATION"] = "1"
        with tempfile.TemporaryDirectory() as tmp:
            artifact_root = Path(tmp) / "20260425-1900" / "artifacts" / "crypto_paper"
            self._write_artifacts(artifact_root)
            result = run_evaluate_crypto_paper_strategy(run_id="20260425-1900", base_path=tmp)
            self.assertEqual(result["status"], "SUCCESS")
            self.assertEqual(result["closed_trades_count"], 1)
            self.assertTrue((artifact_root / "evaluation" / "crypto_paper_trade_log.json").exists())
            self.assertTrue((artifact_root / "evaluation" / "crypto_paper_strategy_metrics.json").exists())

    def test_missing_artifacts_warn_without_crash(self) -> None:
        os.environ["ENABLE_CRYPTO_PAPER_EVALUATION"] = "1"
        with tempfile.TemporaryDirectory() as tmp:
            result = run_evaluate_crypto_paper_strategy(run_id="20260425-1900", base_path=tmp)
            self.assertEqual(result["status"], "SUCCESS")
            self.assertTrue(result["warnings"])

    def test_rerunning_overwrites_outputs_safely(self) -> None:
        os.environ["ENABLE_CRYPTO_PAPER_EVALUATION"] = "1"
        with tempfile.TemporaryDirectory() as tmp:
            artifact_root = Path(tmp) / "20260425-1900" / "artifacts" / "crypto_paper"
            self._write_artifacts(artifact_root)
            first = run_evaluate_crypto_paper_strategy(run_id="20260425-1900", base_path=tmp)
            second = run_evaluate_crypto_paper_strategy(run_id="20260425-1900", base_path=tmp)
            self.assertEqual(first["status"], "SUCCESS")
            self.assertEqual(second["status"], "SUCCESS")
            trade_log = json.loads((artifact_root / "evaluation" / "crypto_paper_trade_log.json").read_text(encoding="utf-8"))
            self.assertEqual(len(trade_log["closed_trades"]), 1)

    def test_does_not_require_api_keys_or_touch_non_crypto_artifacts(self) -> None:
        os.environ["ENABLE_CRYPTO_PAPER_EVALUATION"] = "1"
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "20260425-1900"
            artifact_root = run_root / "artifacts" / "crypto_paper"
            self._write_artifacts(artifact_root)
            equity_artifact = run_root / "artifacts" / "paper.day_close.v1.0.0.json"
            execution_plan = run_root / "artifacts" / "execution.plan.v1.0.0.json"
            equity_artifact.parent.mkdir(parents=True, exist_ok=True)
            equity_artifact.write_text("{}", encoding="utf-8")
            execution_plan.write_text("{}", encoding="utf-8")
            result = run_evaluate_crypto_paper_strategy(run_id="20260425-1900", base_path=tmp)
            self.assertEqual(result["status"], "SUCCESS")
            self.assertEqual(equity_artifact.read_text(encoding="utf-8"), "{}")
            self.assertEqual(execution_plan.read_text(encoding="utf-8"), "{}")


if __name__ == "__main__":
    unittest.main()
