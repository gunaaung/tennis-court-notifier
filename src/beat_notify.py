"""CLI helper for sending deduplicated LINE Flex alerts for BEAT Discovery slots."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from src.checkers import normalize_beat_court_name
from src.formatter import format_line_flex_message, format_line_message
from src.main import load_dotenv_file
from src.models import (
    CourtSlot,
    VENUE_BEAT,
    filter_future_slots,
    now_bangkok,
    parse_target_hours,
)
from src.notifier import send_line_messages
from src.state import find_new_slots, load_state, merge_and_save_state


def parse_slot_arg(raw: str) -> CourtSlot:
    """Parse 'YYYY-MM-DD|HH|Court Name' into a CourtSlot for BEAT Discovery."""
    parts = [p.strip() for p in raw.split("|", 2)]
    if len(parts) != 3 or not parts[0] or not parts[2]:
        raise ValueError(f"Invalid --slot format '{raw}', expected YYYY-MM-DD|HH|Court")
    return CourtSlot(
        venue=VENUE_BEAT,
        date_str=parts[0],
        hour=int(parts[1]),
        court=normalize_beat_court_name(parts[2]),
    )


def parse_slots_from_args(slot_args: list[str], slots_json: str | None) -> list[CourtSlot]:
    """Combine --slot and --slots-json inputs, excluding (Kid) courts by default."""
    parsed: list[CourtSlot] = []
    for raw in slot_args:
        parsed.append(parse_slot_arg(raw))

    if slots_json:
        items = json.loads(slots_json)
        for item in items:
            parsed.append(
                CourtSlot(
                    venue=VENUE_BEAT,
                    date_str=str(item["date"]).strip(),
                    hour=int(item["hour"]),
                    court=normalize_beat_court_name(str(item["court"]).strip()),
                )
            )

    exclude_kid = os.getenv("BEAT_EXCLUDE_KID_COURTS", "true").lower() in {
        "1",
        "true",
        "yes",
    }
    filtered: list[CourtSlot] = []
    seen: set[str] = set()
    for slot in parsed:
        if exclude_kid and "(kid)" in slot.court.lower():
            continue
        if slot.key not in seen:
            seen.add(slot.key)
            filtered.append(slot)
    return sorted(filtered)


def main(argv: list[str] | None = None) -> int:
    """Deduplicate BEAT Discovery slots and send LINE Flex alert if new slots exist."""
    project_root = Path(__file__).resolve().parent.parent
    load_dotenv_file(project_root / ".env")

    parser = argparse.ArgumentParser(
        description="Send deduplicated LINE alerts for BEAT Discovery Tennis slots."
    )
    parser.add_argument(
        "--slot",
        action="append",
        default=[],
        help="Available slot as 'YYYY-MM-DD|HH|Court Name' (repeatable).",
    )
    parser.add_argument(
        "--slots-json",
        default=None,
        help="Optional JSON array of {date, hour, court} objects.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview notification without sending LINE or saving beat_state.json.",
    )
    args = parser.parse_args(argv)

    target_hours = parse_target_hours(os.getenv("TARGET_HOURS", "18,19,20"))
    skip_past = os.getenv("SKIP_PAST_HOURS", "true").lower() in {"1", "true", "yes"}
    state_path = Path(
        os.getenv("BEAT_STATE_FILE", str(project_root / "beat_state.json"))
    )

    now_bkk = now_bangkok()
    raw_slots = parse_slots_from_args(args.slot, args.slots_json)
    current_slots = [
        s
        for s in filter_future_slots(raw_slots, now_bkk, skip_past=skip_past)
        if s.hour in set(target_hours)
    ]

    slots_by_venue = {VENUE_BEAT: current_slots}
    previous_keys = load_state(state_path)
    new_slots = find_new_slots(slots_by_venue, previous_keys)

    print(
        f"[INFO] BEAT Discovery: {len(current_slots)} current slot(s), "
        f"{len(new_slots)} newly available."
    )

    preview_text = format_line_message(
        slots_by_venue=slots_by_venue,
        new_slots=new_slots,
        now_bkk=now_bkk,
        target_hours=target_hours,
    )
    flex_message = format_line_flex_message(
        slots_by_venue=slots_by_venue,
        new_slots=new_slots,
        now_bkk=now_bkk,
        target_hours=target_hours,
    )

    if preview_text:
        print(preview_text)

    if args.dry_run:
        print("[INFO] Dry-run mode: skipped LINE push and state save.")
        return 0

    if flex_message is not None:
        token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
        user_id = os.getenv("LINE_USER_ID", "").strip()
        if not token or not user_id:
            print(
                "[WARN] LINE_CHANNEL_ACCESS_TOKEN or LINE_USER_ID not set; skipping LINE send.",
                file=sys.stderr,
            )
        else:
            send_line_messages(token, user_id, [flex_message])
            print("[INFO] Sent BEAT Discovery LINE notification successfully.")

    merge_and_save_state(
        state_path=state_path,
        previous_keys=previous_keys,
        slots_by_venue=slots_by_venue,
        succeeded_venues={VENUE_BEAT},
        updated_at_iso=now_bkk.isoformat(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
