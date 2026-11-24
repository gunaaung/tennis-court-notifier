"""Data models and date/hour helpers for court availability checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

BANGKOK_TZ = ZoneInfo("Asia/Bangkok")

VENUE_COZY = "Cozy Tennis"
VENUE_OZZY = "Ozzy Court (The Challenge)"
VENUE_BEAT = "BEAT Discovery"
VENUE_SIMOORGH = "Simoorgh Tennis (Bangna)"

VENUE_URLS = {
    VENUE_COZY: "https://book.cozytennis.com/schedule",
    VENUE_OZZY: "https://court.ozzy.asia/court-demo",
    VENUE_BEAT: "https://beatdiscovery.okrabook.com/venues/v2/venue/BEAT%20Discovery",
    VENUE_SIMOORGH: "https://getoncourt.app/en/courts/simoorgh-tennis-academy-bangna/book",
}

VENUE_LINE_OAS = {
    VENUE_COZY: "@cozytennis",
    VENUE_OZZY: "@925atqia",
    VENUE_BEAT: "@BEATDiscovery",
    VENUE_SIMOORGH: "@409mkpcj",
}


@dataclass(frozen=True, order=True)
class CourtSlot:
    """Represents a single 1-hour available court slot."""

    venue: str
    date_str: str  # YYYY-MM-DD
    hour: int      # Start hour (e.g. 19 means 19:00-20:00)
    court: str     # e.g. "Court 1"

    @property
    def key(self) -> str:
        """Unique identifier used for state deduplication."""
        return f"{self.venue}|{self.date_str}|{self.hour:02d}|{self.court}"

    @property
    def venue_url(self) -> str:
        """Direct schedule URL for this venue."""
        return VENUE_URLS.get(self.venue, "")


def now_bangkok() -> datetime:
    """Return current timezone-aware datetime in Asia/Bangkok."""
    return datetime.now(BANGKOK_TZ)


def parse_target_hours(raw: str) -> list[int]:
    """Parse comma-separated start hours such as '19,20' into sorted unique ints."""
    hours: set[int] = set()
    for part in raw.split(","):
        cleaned = part.strip()
        if not cleaned:
            continue
        hour = int(cleaned)
        if not 0 <= hour <= 23:
            raise ValueError(f"Invalid hour value: {hour}")
        hours.add(hour)
    if not hours:
        raise ValueError("TARGET_HOURS must contain at least one hour")
    return sorted(hours)


def get_target_dates(now_bkk: datetime, days_ahead: int) -> list[date]:
    """Return target dates starting from today in Bangkok timezone."""
    if days_ahead < 1:
        raise ValueError("DAYS_AHEAD must be at least 1")
    today = now_bkk.date()
    return [today + timedelta(days=offset) for offset in range(days_ahead)]


def filter_future_slots(
    slots: list[CourtSlot],
    now_bkk: datetime,
    skip_past: bool = True,
) -> list[CourtSlot]:
    """Filter out slots whose start hour has already ended or passed today."""
    if not skip_past:
        return list(slots)

    today_str = now_bkk.date().isoformat()
    current_hour = now_bkk.hour
    return [
        slot
        for slot in slots
        if slot.date_str > today_str or (slot.date_str == today_str and slot.hour >= current_hour)
    ]
