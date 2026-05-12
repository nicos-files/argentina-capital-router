import json
import tempfile
import unittest
from pathlib import Path

from src.manual_execution.execution_tracker import load_manual_execution_log
from src.tools import create_manual_execution_template as cli


REPO_ROOT = Path(__file__).resolve().parents[2]


class CreateManualExecutionTemplateTests(unittest.TestCase):
    def _run(self, args: list[str]) -> int:
        return cli.main(args)

    def test_generates_template_at_explicit_out_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            out = tmp / "exec.json"
            rc = self._run(
                ["--date", "2026-05-12", "--out", str(out)]
            )
            self.assertEqual(rc, 0)
            self.assertTrue(out.exists())

            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(data["as_of"], "2026-05-12")
            self.assertEqual(
                data["execution_log_id"], "manual-executions-2026-05-12"
            )
            self.assertIs(data["manual_review_only"], True)
            self.assertIs(data["live_trading_enabled"], False)
            for exe in data["executions"]:
                self.assertEqual(exe["executed_at"], "2026-05-12")
                self.assertEqual(exe["plan_id"], "2026-05-12")

            # Round-trip through the production loader.
            log = load_manual_execution_log(out)
            self.assertEqual(log.execution_log_id, "manual-executions-2026-05-12")

    def test_refuses_to_overwrite_without_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            out = tmp / "exec.json"
            args = ["--date", "2026-05-12", "--out", str(out)]
            self.assertEqual(self._run(args), 0)
            self.assertEqual(self._run(args), 2)

    def test_overwrite_flag_replaces_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            out = tmp / "exec.json"
            args = ["--date", "2026-05-12", "--out", str(out)]
            self.assertEqual(self._run(args), 0)

            data = json.loads(out.read_text(encoding="utf-8"))
            data["execution_log_id"] = "MUTATED"
            out.write_text(json.dumps(data), encoding="utf-8")

            self.assertEqual(self._run([*args, "--overwrite"]), 0)
            rewritten = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(
                rewritten["execution_log_id"], "manual-executions-2026-05-12"
            )

    def test_invalid_date_returns_usage_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            rc = self._run(
                ["--date", "bad-date", "--out", str(tmp / "x.json")]
            )
            self.assertEqual(rc, 2)


class GitignoreCoversPrivateExecutionLogsTests(unittest.TestCase):
    def test_gitignore_excludes_private_execution_logs(self) -> None:
        gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("snapshots/manual_execution/*.json", gitignore)
        self.assertIn("!snapshots/manual_execution/.gitkeep", gitignore)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
