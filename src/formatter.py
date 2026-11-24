"""Thai message formatter for LINE notifications."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime

from src.models import CourtSlot, VENUE_URLS

THAI_WEEKDAYS = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]
THAI_MONTHS_SHORT = [
    "",
    "ม.ค.",
    "ก.พ.",
    "มี.ค.",
    "เม.ย.",
    "พ.ค.",
    "มิ.ย.",
    "ก.ค.",
    "ส.ค.",
    "ก.ย.",
    "ต.ค.",
    "พ.ย.",
    "ธ.ค.",
]


def format_thai_date(date_str: str, today: date) -> str:
    """Format ISO date string to readable Thai date with relative label."""
    d = date.fromisoformat(date_str)
    weekday = THAI_WEEKDAYS[d.weekday()]
    month = THAI_MONTHS_SHORT[d.month]
    be_year_short = (d.year + 543) % 100
    base = f"วัน{weekday}ที่ {d.day} {month} {be_year_short}"

    delta = (d - today).days
    if delta == 0:
        return f"{base} (วันนี้)"
    if delta == 1:
        return f"{base} (พรุ่งนี้)"
    return base


def _court_sort_key(court_name: str) -> tuple[int, str]:
    digits = "".join(ch for ch in court_name if ch.isdigit())
    return (int(digits) if digits else 999, court_name)


def _format_court_badge(court_name: str, hours: list[int], new_keys: set[str], venue: str, date_str: str) -> str:
    is_new = any(f"{venue}|{date_str}|{h:02d}|{court_name}" in new_keys for h in hours)
    return f"{court_name} 🆕" if is_new else court_name


def format_line_message(
    slots_by_venue: dict[str, list[CourtSlot]],
    new_slots: list[CourtSlot],
    now_bkk: datetime,
    target_hours: list[int],
    include_unchanged: bool = False,
) -> str | None:
    """Build consolidated Thai LINE notification message.

    When include_unchanged is False, only includes (venue, date) sections that
    contain at least one newly available slot, while showing full 2-hour vs 1-hour
    availability context for that (venue, date).
    """
    new_keys = {slot.key for slot in new_slots}
    affected_pairs = {(slot.venue, slot.date_str) for slot in new_slots}

    grouped: dict[str, dict[str, dict[str, set[int]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(set))
    )
    for venue, slots in slots_by_venue.items():
        for slot in slots:
            if include_unchanged or (venue, slot.date_str) in affected_pairs:
                grouped[venue][slot.date_str][slot.court].add(slot.hour)

    if not grouped:
        return None

    start_h = min(target_hours)
    end_h = max(target_hours) + 1
    lines: list[str] = [
        f"🎾 พบคอร์ทเทนนิสว่างช่วง {start_h:02d}:00–{end_h:02d}:00 น.",
        f"อัปเดตเมื่อ {now_bkk.strftime('%H:%M น. (%d/%m/%Y)')}",
    ]

    today = now_bkk.date()
    is_two_hour_window = len(target_hours) == 2 and target_hours[1] == target_hours[0] + 1

    for venue in sorted(grouped.keys()):
        lines.append("")
        lines.append(f"📍 {venue}")
        for date_str in sorted(grouped[venue].keys()):
            lines.append(f"📅 {format_thai_date(date_str, today)}")
            courts_map = grouped[venue][date_str]

            if is_two_hour_window:
                h1, h2 = target_hours[0], target_hours[1]
                both_courts = sorted(
                    [c for c, hrs in courts_map.items() if h1 in hrs and h2 in hrs],
                    key=_court_sort_key,
                )
                only_h1 = sorted(
                    [c for c, hrs in courts_map.items() if h1 in hrs and h2 not in hrs],
                    key=_court_sort_key,
                )
                only_h2 = sorted(
                    [c for c, hrs in courts_map.items() if h2 in hrs and h1 not in hrs],
                    key=_court_sort_key,
                )

                if both_courts:
                    badges = ", ".join(
                        _format_court_badge(c, [h1, h2], new_keys, venue, date_str)
                        for c in both_courts
                    )
                    lines.append(f"  🔥 ว่างติดกัน 2 ชม. ({h1:02d}:00–{h2 + 1:02d}:00): {badges}")
                if only_h1:
                    badges = ", ".join(
                        _format_court_badge(c, [h1], new_keys, venue, date_str)
                        for c in only_h1
                    )
                    lines.append(f"  ⏱️ ว่าง 1 ชม. ({h1:02d}:00–{h1 + 1:02d}:00): {badges}")
                if only_h2:
                    badges = ", ".join(
                        _format_court_badge(c, [h2], new_keys, venue, date_str)
                        for c in only_h2
                    )
                    lines.append(f"  ⏱️ ว่าง 1 ชม. ({h2:02d}:00–{h2 + 1:02d}:00): {badges}")
            else:
                for hour in target_hours:
                    free_courts = sorted(
                        [c for c, hrs in courts_map.items() if hour in hrs],
                        key=_court_sort_key,
                    )
                    if free_courts:
                        badges = ", ".join(
                            _format_court_badge(c, [hour], new_keys, venue, date_str)
                            for c in free_courts
                        )
                        lines.append(f"  ⏱️ {hour:02d}:00–{hour + 1:02d}:00: {badges}")

        url = VENUE_URLS.get(venue)
        if url:
            lines.append(f"🔗 {url}")

    text = "\n".join(lines)
    if len(text) > 4900:
        return text[:4880] + "\n... (ข้อความยาวเกินกำหนด)"
    return text
