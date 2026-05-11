from __future__ import annotations

import subprocess
import sys


def main() -> int:
    cmd = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"]
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
