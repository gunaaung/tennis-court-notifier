"""Thai message formatter and LINE OA deep-link builder."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from urllib.parse import quote

from src.models import CourtSlot, VENUE_LINE_OAS, VENUE_URLS

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

MAX_FLEX_BUTTONS_PER_BUBBLE = 7
MAX_LINE_URI_LENGTH = 1000
MAX_LINE_BUTTON_LABEL_LENGTH = 40
MAX_LINE_ALT_TEXT_LENGTH = 400


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


def build_booking_text(
    date_str: str,
    start_hour: int,
    end_hour: int,
    court: str,
    today: date,
) -> str:
    """Build polite Thai pre-filled message for contacting venue admin to book."""
    d = date.fromisoformat(date_str)
    weekday = THAI_WEEKDAYS[d.weekday()]
    month = THAI_MONTHS_SHORT[d.month]
    delta = (d - today).days
    rel = " (วันนี้)" if delta == 0 else " (พรุ่งนี้)" if delta == 1 else ""
    return (
        f"สวัสดีครับ ขอจองคอร์ทวัน{weekday}ที่ {d.day} {month}{rel} "
        f"เวลา {start_hour:02d}:00-{end_hour:02d}:00 น. ({court}) ครับ"
    )


def build_line_oa_booking_url(oa_id: str, message_text: str) -> str:
    """Build official LINE OA URL scheme link with percent-encoded pre-filled text."""
    encoded_id = quote(oa_id, safe="")
    prefix = f"https://line.me/R/oaMessage/{encoded_id}/?"
    trimmed_text = message_text
    encoded_text = quote(trimmed_text, safe="")
    while len(prefix) + len(encoded_text) > MAX_LINE_URI_LENGTH and trimmed_text:
        trimmed_text = trimmed_text[:-1]
        encoded_text = quote(trimmed_text, safe="")
    return prefix + encoded_text


def _court_sort_key(court_name: str) -> tuple[int, str]:
    digits = "".join(ch for ch in court_name if ch.isdigit())
    return (int(digits) if digits else 999, court_name)


def _format_court_badge(
    court_name: str,
    hours: list[int],
    new_keys: set[str],
    venue: str,
    date_str: str,
) -> str:
    is_new = any(f"{venue}|{date_str}|{h:02d}|{court_name}" in new_keys for h in hours)
    return f"{court_name} 🆕" if is_new else court_name


def _group_affected_slots(
    slots_by_venue: dict[str, list[CourtSlot]],
    new_slots: list[CourtSlot],
    include_unchanged: bool,
) -> dict[str, dict[str, dict[str, set[int]]]]:
    affected_pairs = {(slot.venue, slot.date_str) for slot in new_slots}
    grouped: dict[str, dict[str, dict[str, set[int]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(set))
    )
    for venue, slots in slots_by_venue.items():
        for slot in slots:
            if include_unchanged or (venue, slot.date_str) in affected_pairs:
                grouped[venue][slot.date_str][slot.court].add(slot.hour)
    return grouped


def _find_consecutive_runs(hours: set[int]) -> list[tuple[int, int]]:
    """Convert a set of start hours into maximal consecutive (start, end) ranges."""
    sorted_hours = sorted(hours)
    if not sorted_hours:
        return []
    runs: list[tuple[int, int]] = []
    start = prev = sorted_hours[0]
    for hour in sorted_hours[1:]:
        if hour == prev + 1:
            prev = hour
        else:
            runs.append((start, prev + 1))
            start = prev = hour
    runs.append((start, prev + 1))
    return runs


def _collect_section_details(
    venue: str,
    date_str: str,
    courts_map: dict[str, set[int]],
    new_keys: set[str],
    target_hours: list[int],
    today: date,
) -> tuple[list[str], list[tuple[str, str]]]:
    """Return (summary_lines, [(button_label, booking_text), ...]) for one venue+date."""
    # Group courts by maximal contiguous (start_hour, end_hour) intervals.
    interval_to_courts: dict[tuple[int, int], list[str]] = defaultdict(list)
    for court, hrs in courts_map.items():
        for start_h, end_h in _find_consecutive_runs(hrs):
            interval_to_courts[(start_h, end_h)].append(court)

    sorted_intervals = sorted(
        interval_to_courts.keys(),
        key=lambda span: (-(span[1] - span[0]), span[0]),
    )

    summary_lines: list[str] = []
    booking_options: list[tuple[str, str]] = []
    for start_h, end_h in sorted_intervals:
        duration = end_h - start_h
        courts = sorted(interval_to_courts[(start_h, end_h)], key=_court_sort_key)
        hours_in_span = list(range(start_h, end_h))
        badges = ", ".join(
            _format_court_badge(c, hours_in_span, new_keys, venue, date_str)
            for c in courts
        )
        if duration >= 2:
            summary_lines.append(
                f"🔥 ว่างติดกัน {duration} ชม. ({start_h:02d}:00–{end_h:02d}:00): {badges}"
            )
            for court in courts:
                label = f"💬 จอง {duration} ชม. {court} ({start_h:02d}-{end_h:02d}น.)"
                text = build_booking_text(date_str, start_h, end_h, court, today)
                booking_options.append((label, text))
        else:
            summary_lines.append(
                f"⏱️ ว่าง 1 ชม. ({start_h:02d}:00–{end_h:02d}:00): {badges}"
            )
            for court in courts:
                label = f"💬 จอง {court} ({start_h:02d}:00-{end_h:02d}:00)"
                text = build_booking_text(date_str, start_h, end_h, court, today)
                booking_options.append((label, text))

    return summary_lines, booking_options


def format_line_message(
    slots_by_venue: dict[str, list[CourtSlot]],
    new_slots: list[CourtSlot],
    now_bkk: datetime,
    target_hours: list[int],
    include_unchanged: bool = False,
) -> str | None:
    """Build consolidated Thai plain-text notification summary."""
    grouped = _group_affected_slots(slots_by_venue, new_slots, include_unchanged)
    if not grouped:
        return None

    new_keys = {slot.key for slot in new_slots}
    start_h = min(target_hours)
    end_h = max(target_hours) + 1
    lines: list[str] = [
        f"🎾 พบคอร์ทเทนนิสว่างช่วง {start_h:02d}:00–{end_h:02d}:00 น.",
        f"อัปเดตเมื่อ {now_bkk.strftime('%H:%M น. (%d/%m/%Y)')}",
    ]

    today = now_bkk.date()
    for venue in sorted(grouped.keys()):
        lines.append("")
        lines.append(f"📍 {venue}")
        for date_str in sorted(grouped[venue].keys()):
            lines.append(f"📅 {format_thai_date(date_str, today)}")
            summary_lines, _ = _collect_section_details(
                venue, date_str, grouped[venue][date_str], new_keys, target_hours, today
            )
            for item in summary_lines:
                lines.append(f"  {item}")

        url = VENUE_URLS.get(venue)
        if url:
            lines.append(f"🔗 {url}")

    text = "\n".join(lines)
    if len(text) > 4900:
        return text[:4880] + "\n... (ข้อความยาวเกินกำหนด)"
    return text


def _make_uri_button(label: str, uri: str, primary: bool = True) -> dict:
    return {
        "type": "button",
        "style": "primary" if primary else "secondary",
        "height": "sm",
        "action": {
            "type": "uri",
            "label": label[:MAX_LINE_BUTTON_LABEL_LENGTH],
            "uri": uri,
        },
    }


def format_line_flex_message(
    slots_by_venue: dict[str, list[CourtSlot]],
    new_slots: list[CourtSlot],
    now_bkk: datetime,
    target_hours: list[int],
    include_unchanged: bool = False,
) -> dict | None:
    """Build a LINE Flex Message with tappable LINE OA booking buttons."""
    grouped = _group_affected_slots(slots_by_venue, new_slots, include_unchanged)
    if not grouped:
        return None

    new_keys = {slot.key for slot in new_slots}
    today = now_bkk.date()
    start_h = min(target_hours)
    end_h = max(target_hours) + 1
    bubbles: list[dict] = []

    for venue in sorted(grouped.keys()):
        oa_id = VENUE_LINE_OAS.get(venue)
        schedule_url = VENUE_URLS.get(venue, "")

        for date_str in sorted(grouped[venue].keys()):
            summary_lines, booking_options = _collect_section_details(
                venue, date_str, grouped[venue][date_str], new_keys, target_hours, today
            )
            if not summary_lines:
                continue

            body_contents = [
                {
                    "type": "text",
                    "text": f"📅 {format_thai_date(date_str, today)}",
                    "weight": "bold",
                    "size": "sm",
                    "color": "#1F2937",
                    "wrap": True,
                },
                {
                    "type": "text",
                    "text": f"อัปเดต {now_bkk.strftime('%H:%M น.')}",
                    "size": "xs",
                    "color": "#6B7280",
                    "margin": "xs",
                },
                {"type": "separator", "margin": "md"},
            ]
            for line in summary_lines:
                body_contents.append(
                    {
                        "type": "text",
                        "text": line,
                        "size": "sm",
                        "color": "#111827",
                        "wrap": True,
                        "margin": "md",
                    }
                )

            footer_buttons: list[dict] = []
            if oa_id:
                for label, booking_text in booking_options[:MAX_FLEX_BUTTONS_PER_BUBBLE]:
                    booking_url = build_line_oa_booking_url(oa_id, booking_text)
                    footer_buttons.append(_make_uri_button(label, booking_url, primary=True))
            if schedule_url:
                footer_buttons.append(
                    _make_uri_button("🌐 เปิดดูตารางเว็บ", schedule_url, primary=False)
                )

            bubble: dict = {
                "type": "bubble",
                "header": {
                    "type": "box",
                    "layout": "vertical",
                    "backgroundColor": "#15803D",
                    "paddingAll": "14px",
                    "contents": [
                        {
                            "type": "text",
                            "text": f"🎾 {venue}",
                            "weight": "bold",
                            "size": "md",
                            "color": "#FFFFFF",
                            "wrap": True,
                        },
                        {
                            "type": "text",
                            "text": f"คอร์ทว่างช่วง {start_h:02d}:00–{end_h:02d}:00 น.",
                            "size": "xs",
                            "color": "#DCFCE7",
                            "margin": "xs",
                        },
                    ],
                },
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "paddingAll": "14px",
                    "contents": body_contents,
                },
            }
            if footer_buttons:
                bubble["footer"] = {
                    "type": "box",
                    "layout": "vertical",
                    "spacing": "sm",
                    "paddingAll": "12px",
                    "contents": footer_buttons,
                }
            bubbles.append(bubble)

    if not bubbles:
        return None

    plain_summary = format_line_message(
        slots_by_venue=slots_by_venue,
        new_slots=new_slots,
        now_bkk=now_bkk,
        target_hours=target_hours,
        include_unchanged=include_unchanged,
    )
    alt_text = (
        plain_summary.replace("\n", " ")[:MAX_LINE_ALT_TEXT_LENGTH]
        if plain_summary
        else f"🎾 พบคอร์ทเทนนิสว่างช่วง {start_h:02d}:00–{end_h:02d}:00 น."
    )

    contents: dict = (
        bubbles[0]
        if len(bubbles) == 1
        else {"type": "carousel", "contents": bubbles[:12]}
    )
    return {
        "type": "flex",
        "altText": alt_text,
        "contents": contents,
    }
