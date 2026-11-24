"""Playwright-based availability checkers for all configured tennis venues."""

from __future__ import annotations

import re
from datetime import date
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from src.models import (
    CourtSlot,
    VENUE_BEAT,
    VENUE_COZY,
    VENUE_OZZY,
    VENUE_SIMOORGH,
    VENUE_URLS,
)

COZY_ARIA_PATTERN = re.compile(
    r"^(Court\s+\d+)\s+(\d{1,2}):00[–-](\d{1,2}):00\s+(ว่าง|เต็ม)$"
)
OZZY_HEADER_DATE_PATTERN = re.compile(r"(\d{1,2})\s+([A-Za-z]{3})")
OZZY_TIME_ROW_PATTERN = re.compile(r"(\d{1,2})\.00\s*-\s*(\d{1,2})\.00")

SIMOORGH_VENUE_ID = "01KYP7M56137N4FH9340K04CM6"
BEAT_SPORT_TENNIS_ID = "3"

MONTH_ABBR_TO_NUM = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def parse_cozy_aria_label(label: str) -> tuple[str, int, bool] | None:
    """Parse Cozy Tennis button aria-label into (court_name, start_hour, is_available)."""
    match = COZY_ARIA_PATTERN.match(label.strip())
    if not match:
        return None
    court_name, start_str, _, status = match.groups()
    return court_name, int(start_str), status == "ว่าง"


def parse_ozzy_header_day_month(header_text: str) -> tuple[int, int] | None:
    """Parse Ozzy header like 'Tue - 24 Nov' into (day, month)."""
    match = OZZY_HEADER_DATE_PATTERN.search(header_text)
    if not match:
        return None
    day_num = int(match.group(1))
    month_num = MONTH_ABBR_TO_NUM.get(match.group(2).lower())
    if month_num is None:
        return None
    return day_num, month_num


def parse_ozzy_row_start_hour(time_text: str) -> int | None:
    """Parse Ozzy time cell like '19.00 - 20.00' into start hour int."""
    match = OZZY_TIME_ROW_PATTERN.search(time_text)
    if not match:
        return None
    return int(match.group(1))


def normalize_beat_court_name(title: str) -> str:
    """Shorten 'Tennis Indoor Court 1' -> 'Indoor Court 1' so LINE button labels fit."""
    cleaned = " ".join(title.split())
    if cleaned.lower().startswith("tennis "):
        return cleaned[7:].strip()
    return cleaned


def parse_beat_times_payload(
    payload: dict,
    date_str: str,
    target_hours: set[int],
    exclude_kid_courts: bool = True,
) -> list[CourtSlot]:
    """Parse BEAT Discovery /times JSON response into available Tennis CourtSlots."""
    slots: list[CourtSlot] = []
    for slot in payload.get("slots", []):
        slot_id = slot.get("id")
        if not isinstance(slot_id, int):
            continue
        start_hour = slot_id // 3600
        if start_hour not in target_hours:
            continue
        for court_obj in slot.get("courts", []):
            if court_obj.get("booked") is True:
                continue
            raw_title = str(court_obj.get("title", "")).strip()
            if not raw_title:
                continue
            if exclude_kid_courts and "(kid)" in raw_title.lower():
                continue
            slots.append(
                CourtSlot(
                    venue=VENUE_BEAT,
                    date_str=date_str,
                    hour=start_hour,
                    court=normalize_beat_court_name(raw_title),
                )
            )
    return sorted(slots)


def parse_simoorgh_availability_payload(
    payload: list[dict],
    target_dates: set[str],
    target_hours: set[int],
) -> list[CourtSlot]:
    """Parse GetOnCourt /availability JSON response into available CourtSlots."""
    slots: list[CourtSlot] = []
    for day_entry in payload:
        date_str = str(day_entry.get("date", ""))
        if date_str not in target_dates:
            continue
        for slot in day_entry.get("slots", []):
            if slot.get("available") is not True:
                continue
            slot_seconds = slot.get("slotSeconds")
            if not isinstance(slot_seconds, int):
                continue
            start_hour = slot_seconds // 3600
            if start_hour not in target_hours:
                continue
            court_name = str(slot.get("courtName", "")).strip()
            if not court_name:
                continue
            slots.append(
                CourtSlot(
                    venue=VENUE_SIMOORGH,
                    date_str=date_str,
                    hour=start_hour,
                    court=court_name,
                )
            )
    return sorted(slots)


def check_cozy_tennis(
    page: Page,
    target_dates: list[date],
    target_hours: set[int],
) -> list[CourtSlot]:
    """Scrape Cozy Tennis per-court schedule grid for target dates and hours."""
    url = VENUE_URLS[VENUE_COZY]
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_selector("button[data-date]", timeout=20000)

    choose_court_tab = page.get_by_role("tab", name="เลือกคอร์ทเอง")
    choose_court_tab.wait_for(state="visible", timeout=15000)
    if choose_court_tab.get_attribute("aria-selected") != "true":
        choose_court_tab.click()

    page.wait_for_selector('button[aria-label^="Court "]', timeout=15000)

    slots: list[CourtSlot] = []
    for target_date in target_dates:
        date_iso = target_date.isoformat()
        date_btn = page.locator(f'button[data-date="{date_iso}"]')
        if date_btn.count() == 0:
            continue

        if date_btn.first.get_attribute("aria-pressed") != "true":
            date_btn.first.click()
            page.wait_for_function(
                """(expectedDate) => {
                    const btn = document.querySelector(`button[data-date="${expectedDate}"]`);
                    return btn && btn.getAttribute("aria-pressed") === "true";
                }""",
                arg=date_iso,
                timeout=10000,
            )
            page.wait_for_timeout(250)

        buttons_data = page.eval_on_selector_all(
            'button[aria-label^="Court "]',
            """(els) => els.map(el => ({
                label: el.getAttribute("aria-label") || "",
                disabled: el.hasAttribute("disabled") || el.disabled === true
            }))""",
        )

        for item in buttons_data:
            parsed = parse_cozy_aria_label(item["label"])
            if not parsed:
                continue
            court_name, start_hour, is_available = parsed
            if is_available and not item["disabled"] and start_hour in target_hours:
                slots.append(
                    CourtSlot(
                        venue=VENUE_COZY,
                        date_str=date_iso,
                        hour=start_hour,
                        court=court_name,
                    )
                )

    return sorted(slots)


def check_ozzy_court(
    page: Page,
    target_dates: list[date],
    target_hours: set[int],
) -> list[CourtSlot]:
    """Scrape Ozzy Court schedule table for target dates and hours."""
    url = VENUE_URLS[VENUE_OZZY]
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_selector("#booking-table tbody tr td.court-cell", timeout=25000)

    table_data = page.evaluate(
        """() => {
            const headers = Array.from(
                document.querySelectorAll("#booking-table thead th.date-header")
            ).map(th => ({
                dayId: th.getAttribute("data-day") || "",
                text: (th.textContent || "").trim()
            }));

            const rows = Array.from(
                document.querySelectorAll("#booking-table tbody tr")
            ).map(tr => {
                const timeEl = tr.querySelector("td.time-cell");
                const timeText = timeEl ? (timeEl.textContent || "").trim() : "";
                const availableCells = Array.from(
                    tr.querySelectorAll("td.court-cell.available")
                ).map(td => ({
                    dayId: td.getAttribute("data-day") || "",
                    court: td.getAttribute("data-court") || ""
                }));
                return { timeText, availableCells };
            });

            return { headers, rows };
        }"""
    )

    day_id_to_date_str: dict[str, str] = {}
    target_by_day_month = {(d.day, d.month): d.isoformat() for d in target_dates}
    for header in table_data["headers"]:
        parsed_dm = parse_ozzy_header_day_month(header["text"])
        if parsed_dm and parsed_dm in target_by_day_month:
            day_id_to_date_str[header["dayId"]] = target_by_day_month[parsed_dm]

    slots: list[CourtSlot] = []
    for row in table_data["rows"]:
        start_hour = parse_ozzy_row_start_hour(row["timeText"])
        if start_hour is None or start_hour not in target_hours:
            continue
        for cell in row["availableCells"]:
            date_str = day_id_to_date_str.get(cell["dayId"])
            if not date_str or not cell["court"]:
                continue
            slots.append(
                CourtSlot(
                    venue=VENUE_OZZY,
                    date_str=date_str,
                    hour=start_hour,
                    court=f"Court {cell['court']}",
                )
            )

    return sorted(slots)


def check_beat_discovery(
    page: Page,
    target_dates: list[date],
    target_hours: set[int],
    exclude_kid_courts: bool = True,
) -> list[CourtSlot]:
    """Fetch Tennis-only availability from BEAT Discovery within Playwright session."""
    url = VENUE_URLS[VENUE_BEAT]
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_selector(
        f'button.vn-sport[data-pick="sport"][data-value="{BEAT_SPORT_TENNIS_ID}"]',
        timeout=25000,
    )

    slots: list[CourtSlot] = []
    for target_date in target_dates:
        date_iso = target_date.isoformat()
        payload = page.evaluate(
            """async ({ sportId, dateStr }) => {
                const res = await fetch(
                    `/venues/v2/venue/BEAT%20Discovery/times?sport=${sportId}&date=${dateStr}`,
                    { headers: { "Accept": "application/json" } }
                );
                if (!res.ok) {
                    throw new Error(`HTTP ${res.status}`);
                }
                return await res.json();
            }""",
            {"sportId": BEAT_SPORT_TENNIS_ID, "dateStr": date_iso},
        )
        slots.extend(
            parse_beat_times_payload(
                payload=payload,
                date_str=date_iso,
                target_hours=target_hours,
                exclude_kid_courts=exclude_kid_courts,
            )
        )

    return sorted(slots)


def check_simoorgh_oncourt(
    page: Page,
    target_dates: list[date],
    target_hours: set[int],
    email: str,
    password: str,
) -> list[CourtSlot]:
    """Sign into OnCourt with email/password and fetch Simoorgh availability."""
    login_url = (
        "https://getoncourt.app/en/login"
        "?redirectTo=%2Fen%2Fcourts%2Fsimoorgh-tennis-academy-bangna%2Fbook"
    )
    page.goto(login_url, wait_until="networkidle", timeout=30000)
    email_input = page.locator('input[name="email"]')
    password_input = page.locator('input[name="password"]')
    email_input.wait_for(state="visible", timeout=20000)
    email_input.click()
    email_input.fill(email)
    password_input.click()
    password_input.fill(password)
    sign_in_btn = page.get_by_role("button", name="Sign in", exact=True)
    sign_in_btn.wait_for(state="visible", timeout=10000)
    page.wait_for_timeout(300)
    sign_in_btn.click()
    page.wait_for_url("**/simoorgh-tennis-academy-bangna/book*", timeout=25000)
    page.wait_for_load_state("networkidle", timeout=20000)

    from_date = min(target_dates).isoformat()
    to_date = max(target_dates).isoformat()
    payload = page.evaluate(
        """async ({ venueId, fromDate, toDate }) => {
            const res = await fetch(
                `https://api.getoncourt.app/app/v1/venues/${venueId}/availability?from=${fromDate}&to=${toDate}`,
                { credentials: "include", headers: { "Accept": "application/json" } }
            );
            if (!res.ok) {
                throw new Error(`HTTP ${res.status}`);
            }
            return await res.json();
        }""",
        {"venueId": SIMOORGH_VENUE_ID, "fromDate": from_date, "toDate": to_date},
    )

    return parse_simoorgh_availability_payload(
        payload=payload,
        target_dates={d.isoformat() for d in target_dates},
        target_hours=target_hours,
    )


def fetch_all_available_slots(
    target_dates: list[date],
    target_hours: set[int],
    headless: bool = True,
    enable_beat: bool = False,
    beat_exclude_kid: bool = True,
    oncourt_email: str = "",
    oncourt_password: str = "",
) -> tuple[dict[str, list[CourtSlot]], dict[str, str], dict[str, str]]:
    """Run all venue checkers in a single browser session.

    Returns:
        slots_by_venue: mapping from venue name to list of available CourtSlot
        errors_by_venue: mapping from venue name to error string for any failed check
        skipped_venues: mapping from venue name to skip reason
    """
    slots_by_venue: dict[str, list[CourtSlot]] = {}
    errors_by_venue: dict[str, str] = {}
    skipped_venues: dict[str, str] = {}

    checkers = [
        (VENUE_COZY, lambda page: check_cozy_tennis(page, target_dates, target_hours)),
        (VENUE_OZZY, lambda page: check_ozzy_court(page, target_dates, target_hours)),
    ]

    if enable_beat:
        checkers.append(
            (
                VENUE_BEAT,
                lambda page: check_beat_discovery(
                    page, target_dates, target_hours, exclude_kid_courts=beat_exclude_kid
                ),
            )
        )
    else:
        skipped_venues[VENUE_BEAT] = (
            "Disabled by default (Cloudflare anti-bot challenge blocks automated headless access)"
        )

    if oncourt_email and oncourt_password:
        checkers.append(
            (
                VENUE_SIMOORGH,
                lambda page: check_simoorgh_oncourt(
                    page, target_dates, target_hours, oncourt_email, oncourt_password
                ),
            )
        )
    else:
        skipped_venues[VENUE_SIMOORGH] = (
            "ONCOURT_EMAIL and ONCOURT_PASSWORD are not configured"
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            context = browser.new_context(
                locale="th-TH",
                timezone_id="Asia/Bangkok",
                viewport={"width": 1280, "height": 900},
            )
            for venue_name, checker_fn in checkers:
                page = context.new_page()
                try:
                    slots_by_venue[venue_name] = checker_fn(page)
                except (PlaywrightTimeoutError, Exception) as exc:
                    errors_by_venue[venue_name] = f"{type(exc).__name__}: {exc}"
                finally:
                    page.close()
        finally:
            browser.close()

    return slots_by_venue, errors_by_venue, skipped_venues
