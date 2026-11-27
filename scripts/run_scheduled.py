"""Silent scheduled runner with rotating UTF-8 log and 08:00-19:00 ICT window guard."""

from __future__ import annotations

import argparse
import io
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.main import main as run_notifier_main
from src.models import now_bangkok

MAX_LOG_LINES = 5000
KEEP_LOG_LINES = 2000


def _append_log(log_path: Path, text: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(text)

    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    if len(lines) > MAX_LOG_LINES:
        log_path.write_text("".join(lines[-KEEP_LOG_LINES:]), encoding="utf-8")


def _within_active_window(hour: int, minute: int) -> bool:
    total_minutes = hour * 60 + minute
    return (8 * 60) <= total_minutes <= (19 * 60 + 5)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run tennis court notifier with logging.")
    parser.add_argument(
        "--ignore-window",
        action="store_true",
        help="Run even outside 08:00-19:05 Asia/Bangkok.",
    )
    args = parser.parse_args(argv)

    os.chdir(PROJECT_ROOT)
    log_path = PROJECT_ROOT / "logs" / "notifier.log"
    now_bkk = now_bangkok()
    stamp = now_bkk.strftime("%Y-%m-%d %H:%M:%S")

    if not args.ignore_window and not _within_active_window(now_bkk.hour, now_bkk.minute):
        _append_log(
            log_path,
            f"=== {stamp} +07:00 ===\n[INFO] Outside 08:00-19:05 ICT window; skipped.\n\n",
        )
        return 0

    buffer = io.StringIO()
    exit_code = 1
    try:
        with redirect_stdout(buffer), redirect_stderr(buffer):
            exit_code = run_notifier_main([])
    except Exception as exc:
        buffer.write(f"[ERROR] Unhandled exception: {type(exc).__name__}: {exc}\n")
        exit_code = 1

    _append_log(
        log_path,
        f"=== {stamp} +07:00 (exit={exit_code}) ===\n{buffer.getvalue()}\n",
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
