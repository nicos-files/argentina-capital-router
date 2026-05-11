from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "run_crypto_paper_forward_daily.py"


def _load_wrapper_module():
    spec = importlib.util.spec_from_file_location(
        "run_crypto_paper_forward_daily_under_test",
        _SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load wrapper script for testing.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wrapper = _load_wrapper_module()


class _FakeCompleted:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _seed_canonical_artifacts(artifacts_dir: Path) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    for sub in ("paper_forward", "daily_close", "history", "evaluation"):
        sub_dir = artifacts_dir / sub
        sub_dir.mkdir(parents=True, exist_ok=True)
        (sub_dir / f"{sub}_marker.json").write_text(
            json.dumps({"sub": sub}), encoding="utf-8"
        )
    (artifacts_dir / "crypto_paper_snapshot.json").write_text(
        json.dumps({"cash": 100.0}), encoding="utf-8"
    )
    (artifacts_dir / "crypto_paper_positions.json").write_text(
        json.dumps([]), encoding="utf-8"
    )
    (artifacts_dir / "unrelated.json").write_text(
        json.dumps({"unrelated": True}), encoding="utf-8"
    )


def _write_candidate(tmp: Path) -> Path:
    candidate = tmp / "candidate.json"
    candidate.write_text(
        json.dumps(
            {
                "default_quote_currency": "USDT",
                "strategy": {"enabled": True, "fast_ma_window": 2, "slow_ma_window": 3},
                "symbols": [],
            }
        ),
        encoding="utf-8",
    )
    return candidate


class RunCryptoPaperForwardDailyWrapperTests(unittest.TestCase):
    def _invoke_wrapper(
        self,
        tmp: Path,
        *,
        returncode: int = 0,
        stdout: str = "TOOL-STDOUT",
        stderr: str = "TOOL-STDERR",
        stamp: str = "2026-01-02/030405",
        skip_post_run: bool = True,
    ):
        artifacts_dir = tmp / "artifacts" / "crypto_paper"
        archive_root = tmp / "artifacts" / "crypto_paper" / "archive"
        candidate = _write_candidate(tmp)
        _seed_canonical_artifacts(artifacts_dir)
        fake = _FakeCompleted(returncode=returncode, stdout=stdout, stderr=stderr)
        argv = [
            "--candidate-config",
            str(candidate),
            "--artifacts-dir",
            str(artifacts_dir),
            "--archive-root",
            str(archive_root),
            "--stamp",
            stamp,
        ]
        if skip_post_run:
            argv.append("--skip-post-run")
        with patch.object(wrapper, "run_paper_forward_subprocess", return_value=fake) as mock_run:
            exit_code = wrapper.main(argv)
        archive_dir = archive_root / stamp
        return exit_code, archive_dir, artifacts_dir, candidate, mock_run

    def test_creates_archive_directory(self):
        with TemporaryDirectory() as tmp:
            exit_code, archive_dir, _, _, _ = self._invoke_wrapper(Path(tmp))
            self.assertEqual(exit_code, 0)
            self.assertTrue(archive_dir.is_dir())

    def test_copies_canonical_subdirs_into_archive(self):
        with TemporaryDirectory() as tmp:
            _, archive_dir, _, _, _ = self._invoke_wrapper(Path(tmp))
            for sub in ("paper_forward", "daily_close", "history", "evaluation"):
                marker = archive_dir / sub / f"{sub}_marker.json"
                self.assertTrue(marker.is_file(), f"missing archived marker for {sub}")

    def test_copies_root_level_crypto_paper_json_files(self):
        with TemporaryDirectory() as tmp:
            _, archive_dir, _, _, _ = self._invoke_wrapper(Path(tmp))
            self.assertTrue((archive_dir / "crypto_paper_snapshot.json").is_file())
            self.assertTrue((archive_dir / "crypto_paper_positions.json").is_file())

    def test_does_not_copy_unrelated_root_level_files(self):
        with TemporaryDirectory() as tmp:
            _, archive_dir, _, _, _ = self._invoke_wrapper(Path(tmp))
            self.assertFalse((archive_dir / "unrelated.json").exists())

    def test_does_not_move_or_delete_canonical_outputs(self):
        with TemporaryDirectory() as tmp:
            _, _, artifacts_dir, _, _ = self._invoke_wrapper(Path(tmp))
            for sub in ("paper_forward", "daily_close", "history", "evaluation"):
                marker = artifacts_dir / sub / f"{sub}_marker.json"
                self.assertTrue(marker.is_file(), f"canonical marker for {sub} was removed")
            self.assertTrue((artifacts_dir / "crypto_paper_snapshot.json").is_file())
            self.assertTrue((artifacts_dir / "crypto_paper_positions.json").is_file())
            self.assertTrue((artifacts_dir / "unrelated.json").is_file())

    def test_writes_run_metadata(self):
        with TemporaryDirectory() as tmp:
            _, archive_dir, _, candidate, _ = self._invoke_wrapper(
                Path(tmp), stamp="2026-04-28/120000"
            )
            metadata_path = archive_dir / "run_metadata.json"
            self.assertTrue(metadata_path.is_file())
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["run_id"], "2026-04-28/120000")
            self.assertIn("started_at", payload)
            self.assertIn("finished_at", payload)
            self.assertEqual(payload["exit_code"], 0)
            self.assertEqual(payload["candidate_config"], str(candidate))
            self.assertTrue(payload["paper_only"])
            self.assertFalse(payload["live_trading"])
            self.assertIn("paper_forward", payload["copied"])
            self.assertIn("daily_close", payload["copied"])
            self.assertIn("history", payload["copied"])
            self.assertIn("evaluation", payload["copied"])
            self.assertIn("crypto_paper_snapshot.json", payload["copied"])
            self.assertIn("crypto_paper_positions.json", payload["copied"])

    def test_writes_run_log_with_stdout_and_stderr(self):
        with TemporaryDirectory() as tmp:
            _, archive_dir, _, _, _ = self._invoke_wrapper(
                Path(tmp), stdout="OUT-LINE", stderr="ERR-LINE"
            )
            log_path = archive_dir / "run.log"
            self.assertTrue(log_path.is_file())
            text = log_path.read_text(encoding="utf-8")
            self.assertIn("OUT-LINE", text)
            self.assertIn("ERR-LINE", text)

    def test_returns_underlying_exit_code(self):
        with TemporaryDirectory() as tmp:
            exit_code, _, _, _, _ = self._invoke_wrapper(Path(tmp), returncode=7)
            self.assertEqual(exit_code, 7)

    def test_propagates_required_env_flags_to_subprocess(self):
        with TemporaryDirectory() as tmp:
            _, _, _, _, mock_run = self._invoke_wrapper(Path(tmp))
            self.assertEqual(mock_run.call_count, 1)
            kwargs = mock_run.call_args.kwargs
            env = kwargs.get("env") or {}
            self.assertEqual(env.get("ENABLE_CRYPTO_PAPER_FORWARD"), "1")
            self.assertEqual(env.get("ENABLE_CRYPTO_MARKET_DATA"), "1")

    def test_does_not_touch_execution_plan(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            execution_plan = tmp_path / "execution.plan.json"
            execution_plan.write_text("ORIGINAL-PLAN", encoding="utf-8")
            self._invoke_wrapper(tmp_path)
            self.assertEqual(
                execution_plan.read_text(encoding="utf-8"), "ORIGINAL-PLAN"
            )

    def test_does_not_touch_final_decision(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            final_decision = tmp_path / "final_decision.json"
            final_decision.write_text("ORIGINAL-FINAL", encoding="utf-8")
            self._invoke_wrapper(tmp_path)
            self.assertEqual(
                final_decision.read_text(encoding="utf-8"), "ORIGINAL-FINAL"
            )

    def test_does_not_modify_market_universe_crypto_json(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_dir = tmp_path / "config" / "market_universe"
            config_dir.mkdir(parents=True, exist_ok=True)
            config_file = config_dir / "crypto.json"
            config_file.write_text("ORIGINAL-CONFIG", encoding="utf-8")
            self._invoke_wrapper(tmp_path)
            self.assertEqual(
                config_file.read_text(encoding="utf-8"), "ORIGINAL-CONFIG"
            )

    def test_generate_stamp_format(self):
        stamp = wrapper.generate_stamp()
        self.assertIn("/", stamp)
        date_part, time_part = stamp.split("/", 1)
        self.assertEqual(len(date_part), 10)
        self.assertEqual(date_part[4], "-")
        self.assertEqual(date_part[7], "-")
        self.assertEqual(len(time_part), 6)
        self.assertTrue(time_part.isdigit())

    def test_build_run_command_uses_sys_executable_and_module(self):
        cmd = wrapper.build_run_command(
            candidate_config="cfg.json", artifacts_dir="adir"
        )
        self.assertEqual(cmd[1], "-m")
        self.assertEqual(cmd[2], "src.tools.run_crypto_paper_forward")
        self.assertIn("--candidate-config", cmd)
        self.assertIn("cfg.json", cmd)
        self.assertIn("--artifacts-dir", cmd)
        self.assertIn("adir", cmd)


class RunCryptoPaperForwardDailyPostRunIntegrationTests(unittest.TestCase):
    """Verify post-run reporting (dashboard build + Telegram dispatch) is wired."""

    def _invoke_with_post_run(
        self,
        tmp: Path,
        *,
        wrapper_env_extra: dict[str, str] | None = None,
        main_returncode: int = 0,
        dashboard_returncode: int = 0,
        notify_returncode: int = 0,
        dashboard_raises: BaseException | None = None,
        notify_raises: BaseException | None = None,
        notify_stdout: str = "NOTIFY-OUT",
        extra_argv: list[str] | None = None,
        stamp: str = "2026-05-03/180000",
    ):
        artifacts_dir = tmp / "artifacts" / "crypto_paper"
        archive_root = tmp / "artifacts" / "crypto_paper" / "archive"
        candidate = _write_candidate(tmp)
        _seed_canonical_artifacts(artifacts_dir)
        main_fake = _FakeCompleted(returncode=main_returncode, stdout="MAIN-OUT", stderr="")
        dashboard_fake = _FakeCompleted(returncode=dashboard_returncode, stdout="DASH-OUT", stderr="")
        notify_fake = _FakeCompleted(returncode=notify_returncode, stdout=notify_stdout, stderr="")

        def _dashboard(*args, **kwargs):  # noqa: ANN001
            if dashboard_raises is not None:
                raise dashboard_raises
            return dashboard_fake

        def _notifier(*args, **kwargs):  # noqa: ANN001
            if notify_raises is not None:
                raise notify_raises
            return notify_fake

        env_overrides = wrapper_env_extra or {}
        argv = [
            "--candidate-config",
            str(candidate),
            "--artifacts-dir",
            str(artifacts_dir),
            "--archive-root",
            str(archive_root),
            "--stamp",
            stamp,
        ]
        if extra_argv:
            argv.extend(extra_argv)

        with patch.object(wrapper, "run_paper_forward_subprocess", return_value=main_fake) as mock_main, \
             patch.object(wrapper, "run_dashboard_subprocess", side_effect=_dashboard) as mock_dash, \
             patch.object(wrapper, "run_notifier_subprocess", side_effect=_notifier) as mock_notify, \
             patch.dict("os.environ", env_overrides, clear=False):
            exit_code = wrapper.main(argv)
        archive_dir = archive_root / stamp
        return {
            "exit_code": exit_code,
            "archive_dir": archive_dir,
            "artifacts_dir": artifacts_dir,
            "mock_main": mock_main,
            "mock_dashboard": mock_dash,
            "mock_notify": mock_notify,
        }

    def test_dashboard_subprocess_is_invoked_after_main(self):
        with TemporaryDirectory() as tmp:
            result = self._invoke_with_post_run(Path(tmp))
            self.assertEqual(result["exit_code"], 0)
            self.assertEqual(result["mock_dashboard"].call_count, 1)
            kwargs = result["mock_dashboard"].call_args.kwargs
            self.assertEqual(kwargs.get("artifacts_dir"), str(result["artifacts_dir"]))

    def test_notifier_runs_in_dry_run_when_enable_flag_missing(self):
        with TemporaryDirectory() as tmp:
            result = self._invoke_with_post_run(
                Path(tmp),
                wrapper_env_extra={"ENABLE_CRYPTO_TELEGRAM_ALERTS": "", "TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""},
            )
            self.assertEqual(result["mock_notify"].call_count, 1)
            kwargs = result["mock_notify"].call_args.kwargs
            self.assertTrue(kwargs.get("dry_run"))

    def test_notifier_runs_in_dry_run_when_credentials_missing_even_with_enable_flag(self):
        with TemporaryDirectory() as tmp:
            result = self._invoke_with_post_run(
                Path(tmp),
                wrapper_env_extra={
                    "ENABLE_CRYPTO_TELEGRAM_ALERTS": "1",
                    "TELEGRAM_BOT_TOKEN": "",
                    "TELEGRAM_CHAT_ID": "",
                },
            )
            kwargs = result["mock_notify"].call_args.kwargs
            self.assertTrue(kwargs.get("dry_run"))

    def test_notifier_runs_real_send_when_enable_flag_and_credentials_set(self):
        with TemporaryDirectory() as tmp:
            result = self._invoke_with_post_run(
                Path(tmp),
                wrapper_env_extra={
                    "ENABLE_CRYPTO_TELEGRAM_ALERTS": "1",
                    "TELEGRAM_BOT_TOKEN": "token-not-used-by-mock",
                    "TELEGRAM_CHAT_ID": "987654321",
                },
            )
            kwargs = result["mock_notify"].call_args.kwargs
            self.assertFalse(kwargs.get("dry_run"))

    def test_post_run_failure_does_not_change_main_exit_code(self):
        with TemporaryDirectory() as tmp:
            result = self._invoke_with_post_run(
                Path(tmp),
                main_returncode=0,
                dashboard_raises=RuntimeError("simulated dashboard crash"),
                notify_raises=RuntimeError("simulated notifier crash"),
            )
            self.assertEqual(result["exit_code"], 0)

    def test_post_run_failure_with_main_failure_preserves_main_exit_code(self):
        with TemporaryDirectory() as tmp:
            result = self._invoke_with_post_run(
                Path(tmp),
                main_returncode=7,
                dashboard_raises=RuntimeError("boom"),
                notify_raises=RuntimeError("boom"),
            )
            self.assertEqual(result["exit_code"], 7)

    def test_dashboard_log_and_notify_log_are_archived(self):
        with TemporaryDirectory() as tmp:
            result = self._invoke_with_post_run(Path(tmp))
            self.assertTrue((result["archive_dir"] / "dashboard.log").is_file())
            self.assertTrue((result["archive_dir"] / "notify.log").is_file())
            self.assertIn(
                "DASH-OUT",
                (result["archive_dir"] / "dashboard.log").read_text(encoding="utf-8"),
            )
            self.assertIn(
                "NOTIFY-OUT",
                (result["archive_dir"] / "notify.log").read_text(encoding="utf-8"),
            )

    def test_dashboard_and_semantic_directories_are_archived_when_present(self):
        with TemporaryDirectory() as tmp:
            artifacts_dir = Path(tmp) / "artifacts" / "crypto_paper"
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            # The wrapper's seeding helper does not create dashboard/semantic;
            # simulate them being produced by the (mocked) post-run subprocesses.

            def _dashboard(*args, **kwargs):  # noqa: ANN001
                (artifacts_dir / "dashboard").mkdir(parents=True, exist_ok=True)
                (artifacts_dir / "dashboard" / "index.html").write_text(
                    "<html>paper-only</html>", encoding="utf-8"
                )
                (artifacts_dir / "semantic").mkdir(parents=True, exist_ok=True)
                (artifacts_dir / "semantic" / "crypto_semantic_summary.json").write_text(
                    "{}", encoding="utf-8"
                )
                return _FakeCompleted(returncode=0, stdout="OK", stderr="")

            archive_root = Path(tmp) / "artifacts" / "crypto_paper" / "archive"
            stamp = "2026-05-03/180001"
            candidate = _write_candidate(Path(tmp))
            _seed_canonical_artifacts(artifacts_dir)
            main_fake = _FakeCompleted(returncode=0, stdout="MAIN", stderr="")
            notify_fake = _FakeCompleted(returncode=0, stdout="NOTIFY", stderr="")

            with patch.object(wrapper, "run_paper_forward_subprocess", return_value=main_fake), \
                 patch.object(wrapper, "run_dashboard_subprocess", side_effect=_dashboard), \
                 patch.object(wrapper, "run_notifier_subprocess", return_value=notify_fake):
                wrapper.main(
                    [
                        "--candidate-config", str(candidate),
                        "--artifacts-dir", str(artifacts_dir),
                        "--archive-root", str(archive_root),
                        "--stamp", stamp,
                    ]
                )
            archive_dir = archive_root / stamp
            self.assertTrue((archive_dir / "dashboard" / "index.html").is_file())
            self.assertTrue((archive_dir / "semantic" / "crypto_semantic_summary.json").is_file())
            metadata = json.loads(
                (archive_dir / "run_metadata.json").read_text(encoding="utf-8")
            )
            self.assertIn("dashboard", metadata["copied"])
            self.assertIn("semantic", metadata["copied"])
            self.assertIn("dashboard", metadata["post_run"])
            self.assertIn("notify", metadata["post_run"])
            self.assertTrue(metadata["post_run"]["dashboard"]["ok"])
            self.assertTrue(metadata["post_run"]["notify"]["ok"])

    def test_default_run_does_not_send_real_telegram_without_enable_flag(self):
        with TemporaryDirectory() as tmp:
            result = self._invoke_with_post_run(
                Path(tmp),
                wrapper_env_extra={"ENABLE_CRYPTO_TELEGRAM_ALERTS": "", "TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""},
            )
            metadata = json.loads(
                (result["archive_dir"] / "run_metadata.json").read_text(encoding="utf-8")
            )
            self.assertFalse(metadata["post_run"]["notify"]["telegram_real_send"])
            self.assertTrue(metadata["post_run"]["notify"]["dry_run"])

    def test_should_send_real_telegram_helper(self):
        self.assertFalse(wrapper.should_send_real_telegram({}))
        self.assertFalse(wrapper.should_send_real_telegram({"ENABLE_CRYPTO_TELEGRAM_ALERTS": "1"}))
        self.assertFalse(
            wrapper.should_send_real_telegram(
                {"ENABLE_CRYPTO_TELEGRAM_ALERTS": "1", "TELEGRAM_BOT_TOKEN": "x"}
            )
        )
        self.assertFalse(
            wrapper.should_send_real_telegram(
                {
                    "ENABLE_CRYPTO_TELEGRAM_ALERTS": "0",
                    "TELEGRAM_BOT_TOKEN": "x",
                    "TELEGRAM_CHAT_ID": "y",
                }
            )
        )
        self.assertTrue(
            wrapper.should_send_real_telegram(
                {
                    "ENABLE_CRYPTO_TELEGRAM_ALERTS": "1",
                    "TELEGRAM_BOT_TOKEN": "x",
                    "TELEGRAM_CHAT_ID": "y",
                }
            )
        )

    def test_build_notifier_command_includes_dry_run_flag_when_dry(self):
        cmd = wrapper.build_notifier_command(artifacts_dir="adir", dry_run=True)
        self.assertIn("--dry-run", cmd)
        self.assertEqual(cmd[2], "src.tools.notify_crypto_paper_telegram")

    def test_build_notifier_command_omits_dry_run_when_real(self):
        cmd = wrapper.build_notifier_command(artifacts_dir="adir", dry_run=False)
        self.assertNotIn("--dry-run", cmd)

    def test_build_notifier_command_default_omits_daily_summary(self):
        # The 30-minute cron must NOT pass --daily-summary by default; that
        # used to suppress new actionable BUY/TAKE/STOP alerts whenever the
        # summary message had already been delivered earlier in the day.
        cmd = wrapper.build_notifier_command(artifacts_dir="adir", dry_run=False)
        self.assertNotIn("--daily-summary", cmd)
        self.assertNotIn("--daily-summary-only", cmd)

    def test_build_notifier_command_with_daily_summary_only_appends_flag(self):
        cmd = wrapper.build_notifier_command(
            artifacts_dir="adir", dry_run=False, daily_summary_only=True
        )
        self.assertIn("--daily-summary-only", cmd)
        self.assertNotIn("--daily-summary", cmd)

    def test_wrapper_default_does_not_pass_daily_summary_to_notifier(self):
        # 30-minute cron path: wrapper invoked without --daily-summary-only.
        # The notifier subprocess must NOT receive --daily-summary nor
        # --daily-summary-only, so it sends only new actionable events.
        with TemporaryDirectory() as tmp:
            result = self._invoke_with_post_run(Path(tmp))
            self.assertEqual(result["exit_code"], 0)
            kwargs = result["mock_notify"].call_args.kwargs
            self.assertFalse(kwargs.get("daily_summary_only"))

    def test_wrapper_daily_summary_only_flag_forwards_to_notifier(self):
        # Daily cron path: wrapper invoked with --daily-summary-only must
        # forward that flag to the notifier subprocess.
        with TemporaryDirectory() as tmp:
            result = self._invoke_with_post_run(
                Path(tmp), extra_argv=["--daily-summary-only"]
            )
            self.assertEqual(result["exit_code"], 0)
            kwargs = result["mock_notify"].call_args.kwargs
            self.assertTrue(kwargs.get("daily_summary_only"))

    def test_notify_log_includes_sent_and_skipped_event_ids_when_audit_present(self):
        # Simulate the notifier emitting its single-line JSON audit: the
        # wrapper must surface sent_event_ids and skipped_event_ids into
        # notify.log so the operator can audit each run.
        audit = {
            "ok": True,
            "sent_count": 1,
            "skipped_count": 2,
            "sent_event_ids": [
                {
                    "event_id": "buy:f1:2026-05-05T12:30:07",
                    "event_type": "BUY_FILLED_PAPER",
                    "symbol": "BTCUSDT",
                    "delivery_mode": "sent",
                    "telegram_message_id": 4242,
                }
            ],
            "skipped_event_ids": [
                {
                    "event_id": "rejected:o:1",
                    "reason": "noisy_order_rejected",
                },
                {
                    "event_id": "tp:e:earlier",
                    "reason": "already_sent",
                },
            ],
        }
        with TemporaryDirectory() as tmp:
            result = self._invoke_with_post_run(
                Path(tmp), notify_stdout=json.dumps(audit) + "\n"
            )
            notify_log = (result["archive_dir"] / "notify.log").read_text(
                encoding="utf-8"
            )
            self.assertIn("# sent_count: 1", notify_log)
            self.assertIn("# skipped_count: 2", notify_log)
            self.assertIn("buy:f1:2026-05-05T12:30:07", notify_log)
            self.assertIn("noisy_order_rejected", notify_log)
            self.assertIn("already_sent", notify_log)
            self.assertIn("BUY_FILLED_PAPER", notify_log)


if __name__ == "__main__":
    unittest.main()
