"""Playwright-based availability checkers for Cozy Tennis and Ozzy Court."""

from __future__ import annotations

import re
from datetime import date
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from src.models import CourtSlot, VENUE_COZY, VENUE_OZZY, VENUE_URLS

COZY_ARIA_PATTERN = re.compile(
    r"^(Court\s+\d+)\s+(\d{1,2}):00[–-](\d{1,2}):00\s+(ว่าง|เต็ม)$"
)
OZZY_HEADER_DATE_PATTERN = re.compile(r"(\d{1,2})\s+([A-Za-z]{3})")
OZZY_TIME_ROW_PATTERN = re.compile(r"(\d{1,2})\.00\s*-\s*(\d{1,2})\.00")

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


def fetch_all_available_slots(
    target_dates: list[date],
    target_hours: set[int],
    headless: bool = True,
) -> tuple[dict[str, list[CourtSlot]], dict[str, str]]:
    """Run all venue checkers in a single browser session.

    Returns:
        slots_by_venue: mapping from venue name to list of available CourtSlot
        errors_by_venue: mapping from venue name to error string for any failed check
    """
    slots_by_venue: dict[str, list[CourtSlot]] = {}
    errors_by_venue: dict[str, str] = {}

    checkers = [
        (VENUE_COZY, check_cozy_tennis),
        (VENUE_OZZY, check_ozzy_court),
    ]

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
                    slots_by_venue[venue_name] = checker_fn(page, target_dates, target_hours)
                except (PlaywrightTimeoutError, Exception) as exc:
                    errors_by_venue[venue_name] = f"{type(exc).__name__}: {exc}"
                finally:
                    page.close()
        finally:
            browser.close()

    return slots_by_venue, errors_by_venue
