import json
import tempfile
import unittest
from pathlib import Path

from src.market_data.manual_snapshot import load_manual_market_snapshot
from src.portfolio.portfolio_state import load_manual_portfolio_snapshot
from src.tools import create_manual_snapshot_template as cli


REPO_ROOT = Path(__file__).resolve().parents[2]


class CreateManualSnapshotTemplateTests(unittest.TestCase):
    def _run(self, args: list[str]) -> int:
        return cli.main(args)

    def test_generates_market_snapshot_into_out_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            rc = self._run(
                [
                    "--kind",
                    "market",
                    "--date",
                    "2026-05-12",
                    "--out-dir",
                    str(tmp),
                ]
            )
            self.assertEqual(rc, 0)

            generated = tmp / "market" / "2026-05-12.json"
            self.assertTrue(generated.exists())

            data = json.loads(generated.read_text(encoding="utf-8"))
            self.assertEqual(data["as_of"], "2026-05-12")
            self.assertEqual(data["snapshot_id"], "manual-market-2026-05-12")
            self.assertIs(data["manual_review_only"], True)
            self.assertIs(data["live_trading_enabled"], False)
            for quote in data["quotes"]:
                self.assertEqual(quote["as_of"], "2026-05-12")
            for fx in data["fx_rates"].values():
                self.assertEqual(fx["as_of"], "2026-05-12")
            for rate in data["rates"].values():
                self.assertEqual(rate["as_of"], "2026-05-12")

            # The generated file must be loadable by the production loader.
            snapshot = load_manual_market_snapshot(generated)
            self.assertEqual(snapshot.snapshot_id, "manual-market-2026-05-12")
            self.assertEqual(snapshot.as_of, "2026-05-12")

    def test_generates_portfolio_snapshot_into_out_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            rc = self._run(
                [
                    "--kind",
                    "portfolio",
                    "--date",
                    "2026-05-12",
                    "--out-dir",
                    str(tmp),
                ]
            )
            self.assertEqual(rc, 0)

            generated = tmp / "portfolio" / "2026-05-12.json"
            self.assertTrue(generated.exists())

            data = json.loads(generated.read_text(encoding="utf-8"))
            self.assertEqual(data["as_of"], "2026-05-12")
            self.assertEqual(data["snapshot_id"], "manual-portfolio-2026-05-12")
            self.assertIs(data["manual_review_only"], True)
            self.assertIs(data["live_trading_enabled"], False)

            snapshot = load_manual_portfolio_snapshot(generated)
            self.assertEqual(snapshot.snapshot_id, "manual-portfolio-2026-05-12")
            self.assertEqual(snapshot.as_of, "2026-05-12")

    def test_generates_both_kinds_in_one_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            rc = self._run(
                [
                    "--kind",
                    "both",
                    "--date",
                    "2026-05-12",
                    "--out-dir",
                    str(tmp),
                ]
            )
            self.assertEqual(rc, 0)
            self.assertTrue((tmp / "market" / "2026-05-12.json").exists())
            self.assertTrue((tmp / "portfolio" / "2026-05-12.json").exists())

    def test_refuses_to_overwrite_without_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            args = [
                "--kind",
                "market",
                "--date",
                "2026-05-12",
                "--out-dir",
                str(tmp),
            ]
            self.assertEqual(self._run(args), 0)
            self.assertEqual(self._run(args), 2)

    def test_overwrite_flag_replaces_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            args = [
                "--kind",
                "market",
                "--date",
                "2026-05-12",
                "--out-dir",
                str(tmp),
            ]
            self.assertEqual(self._run(args), 0)
            # Mutate the file so we can detect the rewrite.
            target = tmp / "market" / "2026-05-12.json"
            data = json.loads(target.read_text(encoding="utf-8"))
            data["snapshot_id"] = "MUTATED"
            target.write_text(json.dumps(data), encoding="utf-8")

            self.assertEqual(self._run([*args, "--overwrite"]), 0)
            rewritten = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(rewritten["snapshot_id"], "manual-market-2026-05-12")

    def test_explicit_market_out_path_is_honored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            explicit = tmp / "custom" / "snap.json"
            rc = self._run(
                [
                    "--kind",
                    "market",
                    "--date",
                    "2026-05-12",
                    "--market-out",
                    str(explicit),
                ]
            )
            self.assertEqual(rc, 0)
            self.assertTrue(explicit.exists())

    def test_invalid_date_returns_usage_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            rc = self._run(
                [
                    "--kind",
                    "market",
                    "--date",
                    "not-a-date",
                    "--out-dir",
                    tmp_dir,
                ]
            )
            self.assertEqual(rc, 2)


class TemplateFilesArePackagedTests(unittest.TestCase):
    def test_market_template_loads_when_date_stamped(self) -> None:
        template = (
            REPO_ROOT
            / "config"
            / "data_inputs"
            / "manual_market_snapshot.template.json"
        )
        self.assertTrue(template.exists())
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            rc = cli.main(
                [
                    "--kind",
                    "market",
                    "--date",
                    "2026-05-12",
                    "--out-dir",
                    str(tmp),
                ]
            )
            self.assertEqual(rc, 0)
            load_manual_market_snapshot(tmp / "market" / "2026-05-12.json")

    def test_portfolio_template_loads_when_date_stamped(self) -> None:
        template = (
            REPO_ROOT
            / "config"
            / "portfolio"
            / "manual_portfolio_snapshot.template.json"
        )
        self.assertTrue(template.exists())
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            rc = cli.main(
                [
                    "--kind",
                    "portfolio",
                    "--date",
                    "2026-05-12",
                    "--out-dir",
                    str(tmp),
                ]
            )
            self.assertEqual(rc, 0)
            load_manual_portfolio_snapshot(tmp / "portfolio" / "2026-05-12.json")


class GitignoreCoversPrivateSnapshotsTests(unittest.TestCase):
    def test_gitignore_excludes_private_snapshots(self) -> None:
        gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("snapshots/market/*.json", gitignore)
        self.assertIn("snapshots/portfolio/*.json", gitignore)
        self.assertIn("snapshots/outputs/", gitignore)
        self.assertIn("!snapshots/market/.gitkeep", gitignore)
        self.assertIn("!snapshots/portfolio/.gitkeep", gitignore)
        self.assertIn("!snapshots/outputs/.gitkeep", gitignore)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
