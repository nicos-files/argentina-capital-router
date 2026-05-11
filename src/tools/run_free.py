from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from src.tools.notify_telegram import notify_telegram


ROOT = Path(__file__).resolve().parents[2]
FEATURES_BASE = ROOT / "data" / "processed" / "features"


def run_free(
    date: str,
    hour: str,
    price_profile: str = "free-core",
    fundamentals_profile: str = "free-portfolio",
    start_date: str | None = None,
    timeout_sec: int = 900,
    skip_train: bool = False,
    skip_fundamentals: bool = False,
    execute: bool = False,
    paper: bool = True,
    notify_telegram_enabled: bool = False,
    telegram_bot_token: str | None = None,
    telegram_chat_id: str | None = None,
) -> None:
    run_id = date.replace("-", "") + "-" + hour
    start_date = start_date or _default_start_date(date)
    train_date = date

    commands: list[tuple[str, list[str]]] = [
        (
            "fetch_prices",
            [
                sys.executable,
                "-m",
                "src.execution.ingest.fetch_prices",
                "--date",
                date,
                "--hour",
                hour,
                "--profile",
                price_profile,
                "--free-only",
            ],
        ),
    ]

    if not skip_fundamentals:
        commands.extend(
            [
                (
                    "ingest_fundamentals",
                    [
                        sys.executable,
                        "-m",
                        "src.execution.ingest.ingest_fundamentals",
                        "--date",
                        date,
                        "--hour",
                        hour,
                        "--profile",
                        fundamentals_profile,
                        "--free-only",
                    ],
                ),
                (
                    "process_fundamentals",
                    [
                        sys.executable,
                        "-m",
                        "src.execution.process.process_fundamentals",
                        "--date",
                        date,
                        "--hour",
                        hour,
                    ],
                ),
            ]
        )

    commands.extend(
        [
            (
                "normalize_prices",
                [
                    sys.executable,
                    "-m",
                    "src.execution.process.normalize_prices",
                    "--date",
                    date,
                    "--hour",
                    hour,
                ],
            ),
            (
                "rebuild_features_history",
                [
                    sys.executable,
                    "-m",
                    "src.tools.rebuild_features_history",
                    "--start-date",
                    start_date,
                    "--end-date",
                    date,
                    "--lookback-days",
                    "252",
                    "--indicators-lookback-days",
                    "400",
                    "--hour",
                    hour,
                    "--mode",
                    "train",
                    "--force",
                ],
            ),
        ]
    )

    if not skip_train:
        commands.append(
            (
                "train_model",
                [
                    sys.executable,
                    "-m",
                    "src.pipeline.train_model",
                    "--date",
                    "__TRAIN_DATE__",
                ],
            )
        )

    commands.append(
        (
            "run_all_offline",
            [
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
                "--emit-recommendations",
            ],
        )
    )

    if execute:
        commands.append(
            (
                "run_all_execute_paper",
                [
                    sys.executable,
                    "-m",
                    "src.cli",
                    "run-all",
                    "--mode",
                    "live",
                    "--skip-live-ingest",
                    "--execute",
                    "--paper",
                    "true" if paper else "false",
                    "--date",
                    date,
                    "--hour",
                    hour,
                    "--emit-recommendations",
                ],
            )
        )

    for name, cmd in commands:
        if name == "train_model":
            cmd = [train_date if part == "__TRAIN_DATE__" else part for part in cmd]
        _run_cmd(name, cmd, timeout_sec)
        if name == "rebuild_features_history" and not skip_train:
            train_date = _resolve_feature_date(date)
            print(f"[RUN-FREE] train_date={train_date} (requested_date={date})")

    print("[RUN-FREE] SUCCESS")
    print(f"- run_id: {run_id}")
    print(f"- date: {date}")
    print(f"- hour: {hour}")
    print(f"- start_date: {start_date}")
    print(f"- price_profile: {price_profile}")
    print(f"- fundamentals_profile: {fundamentals_profile}")
    print(f"- execute: {execute}")
    if notify_telegram_enabled:
        result = notify_telegram(
            run_id=run_id,
            base_path="runs",
            bot_token=telegram_bot_token,
            chat_id=telegram_chat_id,
            include_close=False,
        )
        print("[RUN-FREE] TELEGRAM")
        print(f"- chat_id: {result['chat_id']}")
        print(f"- message_length: {result['message_length']}")


def _run_cmd(step: str, cmd: list[str], timeout_sec: int) -> None:
    print(f"[RUN-FREE] step={step} cmd={' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=str(ROOT), timeout=timeout_sec, capture_output=True, text=True)
    if res.returncode != 0:
        if res.stdout:
            print(res.stdout[-4000:])
        if res.stderr:
            print(res.stderr[-4000:])
        raise RuntimeError(f"run-free failed at step={step}")
    if res.stdout:
        print(res.stdout[-2000:])


def _default_start_date(date: str) -> str:
    target = datetime.strptime(date, "%Y-%m-%d")
    return (target - timedelta(days=730)).strftime("%Y-%m-%d")


def _resolve_feature_date(requested_date: str) -> str:
    requested = datetime.strptime(requested_date, "%Y-%m-%d")
    candidates: list[datetime] = []
    for path in FEATURES_BASE.glob("*/*/*/features.parquet"):
        try:
            rel = path.relative_to(FEATURES_BASE)
            date = datetime.strptime("/".join(rel.parts[:3]), "%Y/%m/%d")
        except Exception:
            continue
        if date <= requested:
            candidates.append(date)

    if not candidates:
        raise FileNotFoundError(
            f"No canonical features found under {FEATURES_BASE} on or before {requested_date}"
        )
    return max(candidates).strftime("%Y-%m-%d")
