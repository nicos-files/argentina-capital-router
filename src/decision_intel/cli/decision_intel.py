from __future__ import annotations

import argparse

from src.decision_intel.replay.replayer import replay_run


def main() -> None:
    parser = argparse.ArgumentParser(description="Decision Intelligence CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    replay_parser = subparsers.add_parser("replay", help="Replay a historical run in read-only mode")
    replay_parser.add_argument("--run-id", required=True)
    replay_parser.add_argument("--base-path", default="runs")

    args = parser.parse_args()
    if args.command == "replay":
        report = replay_run(run_id=args.run_id, base_path=args.base_path)
        print(f"{report.match_status} {report.report_path}")


if __name__ == "__main__":
    main()
