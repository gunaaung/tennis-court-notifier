"""Track Suan Luang R.9 booking horizon from furthest date backwards and detect release times."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.checkers import SUANLUANG_TENNIS_COURTS, SUANLUANG_VENUE_ID
from src.main import load_dotenv_file
from src.models import VENUE_SUANLUANG, VENUE_URLS, now_bangkok
from src.notifier import send_line_push

VENUE_HOME_URL = "https://www.courtthai.com/v/suanluang9"
VENUE_AVAIL_URL = "https://www.courtthai.com/api/availability/venue"

THAI_DOW = ["อาทิตย์", "จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์"]


def extract_window_config(html_text: str) -> dict:
    """Extract CourtThai booking window configuration fields from venue SSR HTML."""
    config: dict = {}
    patterns = {
        "windowMode": r'\\?"windowMode\\?":\\?"([^"\\]+)\\?"',
        "windowOpenDow": r'\\?"windowOpenDow\\?":(\d+)',
        "windowOpenHour": r'\\?"windowOpenHour\\?":(\d+)',
        "windowRollingDays": r'\\?"windowRollingDays\\?":(\d+)',
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, html_text)
        if match:
            raw = match.group(1)
            config[key] = int(raw) if raw.isdigit() else raw
    return config


def summarize_tennis_day(payload: dict, date_str: str) -> dict:
    """Summarize booked/available Tennis slots (excluding Tennis Board) for one day."""
    courts_map = payload.get("courts", {})
    booked = 0
    available = 0
    past = 0
    eve_avail: list[str] = []

    for court_id, court_name in SUANLUANG_TENNIS_COURTS.items():
        for entry in courts_map.get(court_id, []):
            state = entry.get("state")
            if state == "booked":
                booked += 1
            elif state == "available":
                available += 1
                time_str = str(entry.get("time", ""))
                if time_str in ("18:00", "19:00"):
                    eve_avail.append(f"{court_name}@{time_str}")
            elif state == "past":
                past += 1

    return {
        "date": date_str,
        "booked": booked,
        "available": available,
        "past": past,
        "eve_avail": sorted(eve_avail),
    }


def detect_release_events(
    previous_days: dict[str, dict],
    current_days: list[dict],
    today: date,
    now_iso: str,
) -> list[dict]:
    """Detect dates transitioning from 0 booked -> >0 booked (booking window opened)."""
    events: list[dict] = []
    for day_info in current_days:
        date_str = day_info["date"]
        prev = previous_days.get(date_str)
        if prev is None:
            continue
        if prev.get("booked", 0) == 0 and day_info["booked"] > 0:
            days_ahead = (date.fromisoformat(date_str) - today).days
            if days_ahead >= 1:
                events.append(
                    {
                        "detected_at": now_iso,
                        "date": date_str,
                        "days_ahead": days_ahead,
                        "prev_booked": prev.get("booked", 0),
                        "new_booked": day_info["booked"],
                        "eve_avail_count": len(day_info["eve_avail"]),
                        "eve_avail": day_info["eve_avail"],
                    }
                )
    return events


def format_window_summary(config: dict) -> str:
    """Format booking window config into readable Thai."""
    mode = config.get("windowMode", "unknown")
    dow = config.get("windowOpenDow")
    hour = config.get("windowOpenHour")
    rolling = config.get("windowRollingDays")
    dow_label = f"วัน{THAI_DOW[dow]}" if isinstance(dow, int) and 0 <= dow <= 6 else str(dow)
    hour_label = f"{hour:02d}:00 น." if isinstance(hour, int) else str(hour)
    return f"โหมด {mode} | เปิดจองทุก{dow_label} เวลา {hour_label} (rolling={rolling} วัน)"


def fetch_horizon_stats(today: date, horizon_days: int = 15) -> tuple[list[dict], dict]:
    """Fetch Tennis availability scanning from furthest date backwards to today."""
    # Scan from furthest date backwards to today as requested.
    target_dates = [
        (today + timedelta(days=offset)).isoformat()
        for offset in range(horizon_days - 1, -1, -1)
    ]
    summaries: list[dict] = []
    window_config: dict = {}

    with httpx.Client(timeout=15.0, follow_redirects=True) as client:
        try:
            home_res = client.get(VENUE_HOME_URL)
            if home_res.status_code == 200:
                window_config = extract_window_config(home_res.text)
        except Exception:
            window_config = {}

        for date_str in target_dates:
            res = client.get(
                VENUE_AVAIL_URL,
                params={"venueId": SUANLUANG_VENUE_ID, "date": date_str},
            )
            res.raise_for_status()
            summaries.append(summarize_tennis_day(res.json(), date_str))

    return summaries, window_config


def append_csv_rows(csv_path: Path, rows: list[dict]) -> None:
    """Append statistics rows to CSV with header if file does not exist."""
    if not rows:
        return
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = csv_path.exists()
    fieldnames = [
        "timestamp_bkk",
        "date",
        "days_ahead",
        "booked",
        "available",
        "eve_18_19_avail",
        "furthest_booked_date",
    ]
    with csv_path.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    load_dotenv_file(PROJECT_ROOT / ".env")

    parser = argparse.ArgumentParser(
        description="Track Suan Luang R.9 booking horizon stats & release times."
    )
    parser.add_argument("--horizon-days", type=int, default=15)
    parser.add_argument("--report", action="store_true", help="Print live horizon report.")
    parser.add_argument("--no-notify", action="store_true", help="Do not send LINE alert.")
    args = parser.parse_args(argv)

    now_bkk = now_bangkok()
    today = now_bkk.date()
    now_iso = now_bkk.isoformat()
    stamp = now_bkk.strftime("%Y-%m-%d %H:%M:%S")

    logs_dir = PROJECT_ROOT / "logs"
    state_path = logs_dir / "suanluang_stats_state.json"
    csv_path = logs_dir / "suanluang_stats.csv"
    releases_path = logs_dir / "suanluang_releases.jsonl"

    summaries_desc, window_config = fetch_horizon_stats(today, args.horizon_days)
    booked_dates = [d["date"] for d in summaries_desc if d["booked"] > 0]
    furthest_booked = max(booked_dates) if booked_dates else None

    previous_state: dict = {}
    if state_path.exists():
        try:
            previous_state = json.loads(state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            previous_state = {}
    previous_days: dict[str, dict] = previous_state.get("days", {})

    release_events = detect_release_events(previous_days, summaries_desc, today, now_iso)

    csv_rows: list[dict] = []
    first_run = not previous_days
    for day_info in summaries_desc:
        date_str = day_info["date"]
        prev = previous_days.get(date_str)
        changed = prev is None or prev.get("booked") != day_info["booked"]
        if first_run or changed:
            csv_rows.append(
                {
                    "timestamp_bkk": stamp,
                    "date": date_str,
                    "days_ahead": (date.fromisoformat(date_str) - today).days,
                    "booked": day_info["booked"],
                    "available": day_info["available"],
                    "eve_18_19_avail": len(day_info["eve_avail"]),
                    "furthest_booked_date": furthest_booked or "",
                }
            )
    append_csv_rows(csv_path, csv_rows)

    if release_events:
        releases_path.parent.mkdir(parents=True, exist_ok=True)
        with releases_path.open("a", encoding="utf-8") as fh:
            for event in release_events:
                fh.write(json.dumps(event, ensure_ascii=False) + "\n")

        if not args.no_notify:
            token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
            user_id = os.getenv("LINE_USER_ID", "").strip()
            if token and user_id:
                lines = [
                    f"📣 {VENUE_SUANLUANG} เริ่มเปิดจองวันใหม่แล้ว!",
                    f"ตรวจพบเมื่อ {now_bkk.strftime('%H:%M น. (%d/%m/%Y)')}",
                ]
                for ev in release_events:
                    lines.append(
                        f"📅 {ev['date']} (ล่วงหน้า {ev['days_ahead']} วัน) — "
                        f"จองแล้ว {ev['new_booked']}/84 ช่อง | 18:00–20:00 ว่าง {ev['eve_avail_count']} ช่อง"
                    )
                lines.append(f"🔗 {VENUE_URLS[VENUE_SUANLUANG]}")
                send_line_push(token, user_id, "\n".join(lines))

    new_state = {
        "updated_at": now_iso,
        "window_config": window_config,
        "furthest_booked_date": furthest_booked,
        "days": {d["date"]: d for d in summaries_desc},
    }
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(new_state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if args.report or True:
        print(f"[INFO] {VENUE_SUANLUANG} Horizon Scan ({stamp} +07:00)")
        if window_config:
            print(f"[INFO] Config: {format_window_summary(window_config)}")
        print(f"[INFO] Furthest booked date: {furthest_booked}")
        print(f"[INFO] Logged {len(csv_rows)} change row(s), {len(release_events)} release event(s).")
        if args.report:
            print("\nDate (furthest -> today) | DaysAhead | Booked/84 | Avail | Eve 18-19 Avail")
            for d in summaries_desc:
                da = (date.fromisoformat(d["date"]) - today).days
                print(
                    f"  {d['date']}             | +{da:<8} | {d['booked']:>2}/84     | {d['available']:>2}    | {len(d['eve_avail'])}"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
