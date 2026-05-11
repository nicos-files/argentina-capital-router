"""Daily crypto paper-forward wrapper that archives a timestamped copy of artifacts.

Paper-only / manual-review only. This wrapper:

- Sets the environment flags required by the existing crypto paper-forward tool
  (``ENABLE_CRYPTO_PAPER_FORWARD=1`` and ``ENABLE_CRYPTO_MARKET_DATA=1``).
- Invokes the unmodified ``src.tools.run_crypto_paper_forward`` module via
  subprocess using ``sys.executable``.
- After the tool finishes, copies the canonical output directories and
  root-level ``crypto_paper_*.json`` artifacts into a timestamped archive
  directory under ``artifacts/crypto_paper/archive/<UTC-stamp>/``.
- Writes ``run_metadata.json`` and ``run.log`` into the same archive directory.
- Returns the same exit code as the underlying tool.

The wrapper does not modify the canonical paths and does not mutate any
production configuration. It does not enable live trading, does not introduce
broker integrations, does not handle API keys, and does not auto-promote any
strategy parameters.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CANONICAL_SUBDIRS: tuple[str, ...] = (
    "paper_forward",
    "daily_close",
    "history",
    "evaluation",
    "semantic",
    "dashboard",
)
CANONICAL_ROOT_FILE_PREFIX: str = "crypto_paper_"
CANONICAL_ROOT_FILE_SUFFIX: str = ".json"

_TELEGRAM_ENABLE_FLAG: str = "ENABLE_CRYPTO_TELEGRAM_ALERTS"
_TELEGRAM_TOKEN_ENV: str = "TELEGRAM_BOT_TOKEN"
_TELEGRAM_CHAT_ID_ENV: str = "TELEGRAM_CHAT_ID"
_DASHBOARD_LOG_NAME: str = "dashboard.log"
_NOTIFY_LOG_NAME: str = "notify.log"
_POST_RUN_TIMEOUT_SEC: int = 120


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the crypto paper-forward tool and copy its canonical artifacts into a "
            "timestamped archive directory. Paper-only / manual-review only."
        )
    )
    parser.add_argument("--candidate-config", required=True)
    parser.add_argument("--artifacts-dir", default="artifacts/crypto_paper")
    parser.add_argument("--archive-root", default="artifacts/crypto_paper/archive")
    parser.add_argument("--stamp", default=None)
    parser.add_argument(
        "--skip-post-run",
        action="store_true",
        help=(
            "Skip the post-run dashboard build and Telegram notifier dispatch. "
            "Used by tests; not recommended for daily operations."
        ),
    )
    parser.add_argument(
        "--daily-summary-only",
        dest="daily_summary_only",
        action="store_true",
        help=(
            "Forward ``--daily-summary-only`` to the Telegram notifier. "
            "Recommended for the once-per-day cron entry: it sends only the "
            "daily portfolio summary and never marks BUY/TAKE/STOP events as "
            "sent. Without this flag (the default for the 30-minute cron), "
            "the notifier sends only new actionable events and never sends "
            "the daily summary."
        ),
    )
    return parser


def generate_stamp() -> str:
    now = datetime.now(timezone.utc)
    return f"{now.strftime('%Y-%m-%d')}/{now.strftime('%H%M%S')}"


def archive_run(*, artifacts_dir: Path, archive_dir: Path) -> list[str]:
    archive_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    if artifacts_dir.is_dir():
        for name in CANONICAL_SUBDIRS:
            source = artifacts_dir / name
            if source.is_dir():
                destination = archive_dir / name
                shutil.copytree(source, destination, dirs_exist_ok=True)
                copied.append(name)
        for entry in sorted(artifacts_dir.iterdir()):
            if not entry.is_file():
                continue
            if not entry.name.startswith(CANONICAL_ROOT_FILE_PREFIX):
                continue
            if not entry.name.endswith(CANONICAL_ROOT_FILE_SUFFIX):
                continue
            shutil.copy2(entry, archive_dir / entry.name)
            copied.append(entry.name)
    return copied


def get_git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    commit = (result.stdout or "").strip()
    return commit or None


def build_run_command(*, candidate_config: str, artifacts_dir: str) -> list[str]:
    return [
        sys.executable,
        "-m",
        "src.tools.run_crypto_paper_forward",
        "--candidate-config",
        candidate_config,
        "--artifacts-dir",
        artifacts_dir,
    ]


def build_dashboard_command(*, artifacts_dir: str) -> list[str]:
    return [
        sys.executable,
        "-m",
        "src.tools.build_crypto_paper_dashboard",
        "--artifacts-dir",
        artifacts_dir,
        "--rebuild-semantic",
    ]


def build_notifier_command(
    *,
    artifacts_dir: str,
    dry_run: bool,
    daily_summary_only: bool = False,
) -> list[str]:
    """Build the argv for the Telegram notifier subprocess.

    By default (``daily_summary_only=False``) the command sends only new
    actionable events and never sends the daily summary; this is the correct
    invocation for the 30-minute cron and avoids re-sending the summary on
    every run.

    With ``daily_summary_only=True`` the command appends ``--daily-summary-only``
    to the notifier; this is the correct invocation for the once-per-day cron
    and never marks BUY/TAKE/STOP events as sent.

    The legacy ``--daily-summary`` flag (summary plus pending alerts) is
    intentionally not emitted here; callers that need it can run the notifier
    directly.
    """

    cmd = [
        sys.executable,
        "-m",
        "src.tools.notify_crypto_paper_telegram",
        "--artifacts-dir",
        artifacts_dir,
    ]
    if daily_summary_only:
        cmd.append("--daily-summary-only")
    if dry_run:
        cmd.append("--dry-run")
    return cmd


def should_send_real_telegram(env: dict[str, str]) -> bool:
    """Return True only if the env unambiguously authorises a real Telegram send.

    Real send requires *all three* of:
    - ``ENABLE_CRYPTO_TELEGRAM_ALERTS=1``
    - non-empty ``TELEGRAM_BOT_TOKEN``
    - non-empty ``TELEGRAM_CHAT_ID``

    Otherwise the wrapper falls back to dry-run, which never contacts the
    network and never requires credentials.
    """

    enabled = str(env.get(_TELEGRAM_ENABLE_FLAG) or "").strip()
    token = str(env.get(_TELEGRAM_TOKEN_ENV) or "").strip()
    chat = str(env.get(_TELEGRAM_CHAT_ID_ENV) or "").strip()
    return enabled == "1" and bool(token) and bool(chat)


def run_paper_forward_subprocess(
    *,
    candidate_config: str,
    artifacts_dir: str,
    env: dict[str, str],
) -> subprocess.CompletedProcess:
    cmd = build_run_command(candidate_config=candidate_config, artifacts_dir=artifacts_dir)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def run_dashboard_subprocess(
    *,
    artifacts_dir: str,
    env: dict[str, str],
) -> subprocess.CompletedProcess:
    cmd = build_dashboard_command(artifacts_dir=artifacts_dir)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=_POST_RUN_TIMEOUT_SEC,
    )


def run_notifier_subprocess(
    *,
    artifacts_dir: str,
    env: dict[str, str],
    dry_run: bool,
    daily_summary_only: bool = False,
) -> subprocess.CompletedProcess:
    cmd = build_notifier_command(
        artifacts_dir=artifacts_dir,
        dry_run=dry_run,
        daily_summary_only=daily_summary_only,
    )
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=_POST_RUN_TIMEOUT_SEC,
    )


def write_run_log(*, archive_dir: Path, completed: subprocess.CompletedProcess) -> Path:
    log_path = archive_dir / "run.log"
    parts = [
        "# stdout",
        completed.stdout or "",
        "# stderr",
        completed.stderr or "",
    ]
    log_path.write_text("\n".join(parts), encoding="utf-8")
    return log_path


def _write_subprocess_log(
    *,
    archive_dir: Path,
    name: str,
    summary: dict[str, Any],
) -> Path:
    log_path = archive_dir / name
    parts = [
        f"# command",
        " ".join(str(part) for part in summary.get("cmd") or []),
        f"# exit_code: {summary.get('exit_code')}",
        f"# error: {summary.get('error') or ''}",
    ]
    if "sent_event_ids" in summary or "skipped_event_ids" in summary:
        parts.extend(
            [
                f"# sent_count: {summary.get('sent_count')}",
                f"# skipped_count: {summary.get('skipped_count')}",
                f"# sent_event_ids: {json.dumps(summary.get('sent_event_ids') or [], ensure_ascii=False)}",
                f"# skipped_event_ids: {json.dumps(summary.get('skipped_event_ids') or [], ensure_ascii=False)}",
            ]
        )
    parts.extend(
        [
            "# stdout",
            summary.get("stdout") or "",
            "# stderr",
            summary.get("stderr") or "",
        ]
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("\n".join(parts), encoding="utf-8")
    return log_path


def _parse_notifier_audit(stdout: str) -> dict[str, Any] | None:
    """Best-effort parse of the notifier's single-line JSON audit on stdout.

    Returns ``None`` when the stdout cannot be parsed; the caller treats this
    as a missing audit (notifier crashed or wrote unexpected output) and the
    notify.log still contains the raw stdout/stderr for diagnosis.
    """

    if not stdout:
        return None
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{") or not line.endswith("}"):
            continue
        try:
            parsed = json.loads(line)
        except Exception:
            continue
        if isinstance(parsed, dict) and (
            "sent_event_ids" in parsed or "skipped_event_ids" in parsed
        ):
            return parsed
    return None


def _safe_post_run_step(
    *,
    runner,
    cmd_builder,
    label: str,
    artifacts_dir: str,
    env: dict[str, str],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Invoke a post-run subprocess defensively. Never raises.

    The returned dict is suitable for embedding in run metadata and writing as
    a sidecar log file. Failures are recorded in ``error`` / ``exit_code``
    without propagating to the caller.
    """

    summary: dict[str, Any] = {
        "label": label,
        "ok": False,
        "exit_code": None,
        "error": None,
        "stdout": "",
        "stderr": "",
        "cmd": cmd_builder(artifacts_dir=artifacts_dir) if cmd_builder is not None else [],
    }
    if extra:
        summary.update(extra)
    try:
        completed = runner()
        summary["exit_code"] = int(getattr(completed, "returncode", 1))
        summary["stdout"] = getattr(completed, "stdout", "") or ""
        summary["stderr"] = getattr(completed, "stderr", "") or ""
        summary["ok"] = summary["exit_code"] == 0
    except Exception as exc:  # pragma: no cover - defensive
        summary["error"] = repr(exc)
    return summary


def write_run_metadata(
    *,
    archive_dir: Path,
    metadata: dict[str, Any],
) -> Path:
    metadata_path = archive_dir / "run_metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, sort_keys=True, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return metadata_path


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    artifacts_dir = Path(args.artifacts_dir)
    archive_root = Path(args.archive_root)
    stamp = args.stamp or generate_stamp()
    archive_dir = archive_root / stamp

    env = os.environ.copy()
    env["ENABLE_CRYPTO_PAPER_FORWARD"] = "1"
    env["ENABLE_CRYPTO_MARKET_DATA"] = "1"
    env.setdefault("PYTHONPATH", ".")

    started_at = datetime.now(timezone.utc).isoformat()
    completed = run_paper_forward_subprocess(
        candidate_config=str(args.candidate_config),
        artifacts_dir=str(artifacts_dir),
        env=env,
    )
    finished_at = datetime.now(timezone.utc).isoformat()

    # --- Post-run reporting (never fails the main run) ----------------------
    # Build the dashboard and dispatch the notifier (dry-run by default)
    # before archiving, so the archived snapshot includes the freshly built
    # dashboard/, semantic/ and the post-run logs.
    dashboard_summary: dict[str, Any] = {
        "label": "dashboard",
        "ok": False,
        "skipped": True,
        "reason": "skipped_by_flag",
        "exit_code": None,
        "stdout": "",
        "stderr": "",
        "cmd": [],
        "error": None,
    }
    notify_summary: dict[str, Any] = {
        "label": "notify",
        "ok": False,
        "skipped": True,
        "reason": "skipped_by_flag",
        "exit_code": None,
        "stdout": "",
        "stderr": "",
        "cmd": [],
        "error": None,
        "dry_run": True,
        "telegram_real_send": False,
    }

    if not args.skip_post_run:
        dashboard_summary = _safe_post_run_step(
            label="dashboard",
            runner=lambda: run_dashboard_subprocess(
                artifacts_dir=str(artifacts_dir), env=env
            ),
            cmd_builder=build_dashboard_command,
            artifacts_dir=str(artifacts_dir),
            env=env,
        )

        real_send = should_send_real_telegram(env)
        dry_run = not real_send
        daily_summary_only = bool(args.daily_summary_only)
        notify_summary = _safe_post_run_step(
            label="notify",
            runner=lambda: run_notifier_subprocess(
                artifacts_dir=str(artifacts_dir),
                env=env,
                dry_run=dry_run,
                daily_summary_only=daily_summary_only,
            ),
            cmd_builder=lambda artifacts_dir: build_notifier_command(
                artifacts_dir=artifacts_dir,
                dry_run=dry_run,
                daily_summary_only=daily_summary_only,
            ),
            artifacts_dir=str(artifacts_dir),
            env=env,
            extra={
                "dry_run": dry_run,
                "telegram_real_send": real_send,
                "daily_summary_only": daily_summary_only,
            },
        )
        # Surface notifier audit fields (event ids + reasons) into the wrapper
        # summary so the archived notify.log and run_metadata.json record what
        # was actually delivered. Parse defensively: notifier prints a single
        # JSON line on stdout.
        notify_audit = _parse_notifier_audit(notify_summary.get("stdout") or "")
        if notify_audit is not None:
            notify_summary["sent_event_ids"] = notify_audit.get("sent_event_ids") or []
            notify_summary["skipped_event_ids"] = notify_audit.get("skipped_event_ids") or []
            notify_summary["sent_count"] = notify_audit.get("sent_count")
            notify_summary["skipped_count"] = notify_audit.get("skipped_count")

    # --- Archive ------------------------------------------------------------
    archive_dir.mkdir(parents=True, exist_ok=True)
    copied = archive_run(artifacts_dir=artifacts_dir, archive_dir=archive_dir)

    log_path = write_run_log(archive_dir=archive_dir, completed=completed)
    dashboard_log_path = _write_subprocess_log(
        archive_dir=archive_dir, name=_DASHBOARD_LOG_NAME, summary=dashboard_summary
    )
    notify_log_path = _write_subprocess_log(
        archive_dir=archive_dir, name=_NOTIFY_LOG_NAME, summary=notify_summary
    )

    metadata = {
        "run_id": stamp,
        "started_at": started_at,
        "finished_at": finished_at,
        "exit_code": int(completed.returncode),
        "candidate_config": str(args.candidate_config),
        "artifacts_dir": str(artifacts_dir),
        "archive_dir": str(archive_dir),
        "archive_root": str(archive_root),
        "copied": copied,
        "git_commit": get_git_commit(),
        "paper_only": True,
        "live_trading": False,
        "post_run": {
            "dashboard": {
                k: v for k, v in dashboard_summary.items() if k not in ("stdout", "stderr")
            },
            "notify": {
                k: v for k, v in notify_summary.items() if k not in ("stdout", "stderr")
            },
        },
    }
    metadata_path = write_run_metadata(archive_dir=archive_dir, metadata=metadata)

    sys.stdout.write(completed.stdout or "")
    sys.stderr.write(completed.stderr or "")
    sys.stdout.write(f"[ARCHIVE] {archive_dir}\n")
    sys.stdout.write(f"[ARCHIVE-METADATA] {metadata_path}\n")
    sys.stdout.write(f"[ARCHIVE-LOG] {log_path}\n")
    sys.stdout.write(
        f"[POST-RUN] dashboard ok={dashboard_summary.get('ok')} "
        f"exit={dashboard_summary.get('exit_code')} log={dashboard_log_path}\n"
    )
    sys.stdout.write(
        f"[POST-RUN] notify ok={notify_summary.get('ok')} "
        f"dry_run={notify_summary.get('dry_run')} "
        f"real_send={notify_summary.get('telegram_real_send')} "
        f"exit={notify_summary.get('exit_code')} log={notify_log_path}\n"
    )
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
