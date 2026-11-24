"""Main CLI entrypoint for checking tennis court availability and notifying LINE."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from src.checkers import fetch_all_available_slots
from src.formatter import format_line_flex_message, format_line_message
from src.models import (
    CourtSlot,
    filter_future_slots,
    get_target_dates,
    now_bangkok,
    parse_target_hours,
)
from src.notifier import send_line_messages
from src.state import find_new_slots, load_state, merge_and_save_state


def load_dotenv_file(env_path: Path) -> None:
    """Populate os.environ from a local .env file without overriding existing vars."""
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Check tennis court availability and send LINE Messaging API alerts."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check sites and print output without updating state or sending LINE.",
    )
    parser.add_argument(
        "--force-notify",
        action="store_true",
        help="Send a LINE summary even if all available slots were already notified (or send status if none).",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run Playwright with a visible browser window for debugging.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Execute court check, compare with prior state, and notify LINE on new slots."""
    load_dotenv_file(Path(".env"))
    args = parse_args(argv)

    days_ahead = int(os.getenv("DAYS_AHEAD", "2"))
    target_hours = parse_target_hours(os.getenv("TARGET_HOURS", "18,19,20"))
    skip_past = os.getenv("SKIP_PAST_HOURS", "true").lower() in {"1", "true", "yes"}
    beat_exclude_kid = os.getenv("BEAT_EXCLUDE_KID_COURTS", "true").lower() in {
        "1",
        "true",
        "yes",
    }
    oncourt_email = os.getenv("ONCOURT_EMAIL", "").strip()
    oncourt_password = os.getenv("ONCOURT_PASSWORD", "").strip()
    state_path = Path(os.getenv("STATE_FILE", "state.json"))

    now_bkk = now_bangkok()
    target_dates = get_target_dates(now_bkk, days_ahead)

    print(
        f"[INFO] Checking dates {[d.isoformat() for d in target_dates]} "
        f"for hours {target_hours} (Bangkok time: {now_bkk.strftime('%Y-%m-%d %H:%M:%S')})"
    )

    raw_slots_by_venue, errors_by_venue, skipped_venues = fetch_all_available_slots(
        target_dates=target_dates,
        target_hours=set(target_hours),
        headless=not args.headed,
        beat_exclude_kid=beat_exclude_kid,
        oncourt_email=oncourt_email,
        oncourt_password=oncourt_password,
    )

    for venue, reason in skipped_venues.items():
        print(f"[INFO] Skipped {venue}: {reason}")

    for venue, err in errors_by_venue.items():
        print(f"[WARN] Failed checking {venue}: {err}", file=sys.stderr)

    slots_by_venue: dict[str, list[CourtSlot]] = {
        venue: filter_future_slots(slots, now_bkk, skip_past=skip_past)
        for venue, slots in raw_slots_by_venue.items()
    }

    total_found = sum(len(slots) for slots in slots_by_venue.values())
    print(f"[INFO] Found {total_found} available 1-hour slot(s) across succeeded venues.")
    for venue, slots in slots_by_venue.items():
        print(f"  - {venue}: {len(slots)} slot(s)")
        for slot in slots:
            print(f"      {slot.date_str} {slot.hour:02d}:00-{slot.hour + 1:02d}:00 {slot.court}")

    if not slots_by_venue and errors_by_venue:
        print("[ERROR] All venue checks failed.", file=sys.stderr)
        return 1

    previous_keys = load_state(state_path)
    new_slots = find_new_slots(slots_by_venue, previous_keys)
    print(f"[INFO] Newly available slot(s): {len(new_slots)}")

    preview_text = format_line_message(
        slots_by_venue=slots_by_venue,
        new_slots=new_slots,
        now_bkk=now_bkk,
        target_hours=target_hours,
        include_unchanged=args.force_notify,
    )
    flex_message = format_line_flex_message(
        slots_by_venue=slots_by_venue,
        new_slots=new_slots,
        now_bkk=now_bkk,
        target_hours=target_hours,
        include_unchanged=args.force_notify,
    )

    line_messages: list[dict] = []
    if flex_message is not None:
        line_messages = [flex_message]
    elif args.force_notify:
        date_labels = ", ".join(d.isoformat() for d in target_dates)
        preview_text = (
            f"🎾 ทดสอบระบบแจ้งเตือนคอร์ทเทนนิส\n"
            f"เช็กวันที่ {date_labels} ช่วง {min(target_hours):02d}:00–{max(target_hours) + 1:02d}:00 น.\n"
            f"ผลลัพธ์: ยังไม่มีคอร์ทว่างในขณะนี้ค่ะ"
        )
        line_messages = [{"type": "text", "text": preview_text}]

    if preview_text:
        print("\n--- Notification Preview ---")
        print(preview_text)
        print("----------------------------\n")

    if args.dry_run:
        print("[INFO] Dry-run mode: skipped LINE push and state save.")
        return 0

    if line_messages:
        token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
        user_id = os.getenv("LINE_USER_ID", "").strip()
        if not token or not user_id:
            print(
                "[WARN] LINE_CHANNEL_ACCESS_TOKEN or LINE_USER_ID not set; skipping LINE send.",
                file=sys.stderr,
            )
        else:
            send_line_messages(token, user_id, line_messages)
            print("[INFO] Sent LINE push notification successfully.")

    merge_and_save_state(
        state_path=state_path,
        previous_keys=previous_keys,
        slots_by_venue=slots_by_venue,
        succeeded_venues=set(slots_by_venue.keys()),
        updated_at_iso=now_bkk.isoformat(),
    )
    print(f"[INFO] Saved updated state to {state_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
