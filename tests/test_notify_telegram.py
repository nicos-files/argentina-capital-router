import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.tools.notify_telegram import build_telegram_message, notify_telegram


class NotifyTelegramTests(unittest.TestCase):
    def test_build_telegram_message_includes_recommendations_and_close(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            run_root = repo_root / "runs" / "20260422-1820" / "artifacts"
            run_root.mkdir(parents=True, exist_ok=True)
            rec_path = run_root / "recommendation.outputs.v1.0.0.json"
            close_path = run_root / "paper.day_close.v1.0.0.json"
            rec_path.write_text(
                json.dumps(
                    {
                        "run_id": "20260422-1820",
                        "asof_date": "2026-04-21",
                        "execution_date": "2026-04-22",
                        "execution_hour": "1820",
                        "recommendations": [
                            {
                                "horizon": "INTRADAY",
                                "action": "BUY",
                                "asset_id": "AAPL",
                                "qty_target": 0.5,
                                "usd_target_effective": 50.0,
                                "expected_return_net_pct": 0.02,
                                "fees_estimated_usd": 2.0,
                            }
                        ],
                        "cash_summary": {
                            "INTRADAY": {"cash_retained_usd": 48.0},
                            "LONG_TERM": {"cash_retained_usd": 100.0},
                        },
                    }
                ),
                encoding="utf-8",
            )
            close_path.write_text(
                json.dumps(
                    {
                        "equity_before_usd": 100.0,
                        "equity_after_usd": 101.5,
                        "net_pnl_usd": 1.5,
                        "fees_total_usd": 2.0,
                    }
                ),
                encoding="utf-8",
            )

            import src.tools.notify_telegram as module

            original_root = module.ROOT
            module.ROOT = repo_root
            try:
                message = build_telegram_message("20260422-1820", include_close=True)
            finally:
                module.ROOT = original_root

            self.assertIn("quant-trading-bot | run 20260422-1820", message)
            self.assertIn("BUY AAPL", message)
            self.assertIn("CIERRE:", message)
            self.assertIn("net_pnl_usd=1.50", message)

    def test_notify_telegram_uses_env_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            run_root = repo_root / "runs" / "20260422-1820" / "artifacts"
            run_root.mkdir(parents=True, exist_ok=True)
            (run_root / "recommendation.outputs.v1.0.0.json").write_text(
                json.dumps(
                    {
                        "run_id": "20260422-1820",
                        "asof_date": "2026-04-21",
                        "recommendations": [],
                        "cash_summary": {},
                    }
                ),
                encoding="utf-8",
            )

            import src.tools.notify_telegram as module

            original_root = module.ROOT
            module.ROOT = repo_root
            try:
                with patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "token", "TELEGRAM_CHAT_ID": "123456"}):
                    with patch("src.tools.notify_telegram.send_telegram_message", return_value={"ok": True}) as mocked:
                        summary = notify_telegram("20260422-1820", include_close=False)
            finally:
                module.ROOT = original_root

            self.assertTrue(summary["ok"])
            self.assertEqual(summary["chat_id"], "**3456")
            mocked.assert_called_once()


if __name__ == "__main__":
    unittest.main()
