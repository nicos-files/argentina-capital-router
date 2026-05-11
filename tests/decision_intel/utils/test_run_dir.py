import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.utils.io import ensure_run_dir, validate_run_write_path


class RunDirTests(unittest.TestCase):
    def test_ensure_run_dir_idempotent(self):
        with TemporaryDirectory() as tmp:
            run_root = ensure_run_dir("run-1", base_path=tmp)
            self.assertTrue((run_root / "manifests").exists())
            self.assertTrue((run_root / "logs").exists())
            self.assertTrue((run_root / "artifacts").exists())
            self.assertTrue((run_root / "reports").exists())

            run_root_again = ensure_run_dir("run-1", base_path=tmp)
            self.assertEqual(run_root, run_root_again)

    def test_validate_run_write_path_allows_within_run(self):
        with TemporaryDirectory() as tmp:
            run_root = ensure_run_dir("run-2", base_path=tmp)
            target = run_root / "artifacts" / "decisions.parquet"
            resolved = validate_run_write_path("run-2", target, base_path=tmp)
            self.assertEqual(resolved, target.resolve())

    def test_validate_run_write_path_blocks_outside(self):
        with TemporaryDirectory() as tmp:
            ensure_run_dir("run-3", base_path=tmp)
            outside = Path(tmp).parent / "other.txt"
            with self.assertRaises(ValueError):
                validate_run_write_path("run-3", outside, base_path=tmp)

    def test_validate_run_id_rejects_path_segments(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                ensure_run_dir("bad/run", base_path=tmp)


if __name__ == "__main__":
    unittest.main()
