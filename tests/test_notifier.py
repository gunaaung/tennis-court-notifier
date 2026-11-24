"""Unit tests for court availability parsing, state deduplication, and formatting."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from src.checkers import (
    parse_cozy_aria_label,
    parse_ozzy_header_day_month,
    parse_ozzy_row_start_hour,
)
from src.formatter import format_line_message
from src.models import BANGKOK_TZ, CourtSlot, VENUE_COZY, VENUE_OZZY, filter_future_slots
from src.state import find_new_slots, load_state, merge_and_save_state


class ParsingTests(unittest.TestCase):
    def test_parse_cozy_aria_label(self) -> None:
        self.assertEqual(
            parse_cozy_aria_label("Court 2 19:00–20:00 ว่าง"),
            ("Court 2", 19, True),
        )
        self.assertEqual(
            parse_cozy_aria_label("Court 4 20:00-21:00 เต็ม"),
            ("Court 4", 20, False),
        )
        self.assertIsNone(parse_cozy_aria_label("Invalid label"))

    def test_parse_ozzy_header_and_row(self) -> None:
        self.assertEqual(parse_ozzy_header_day_month("Tue - 24 Nov"), (24, 11))
        self.assertEqual(parse_ozzy_header_day_month("Tue - 1 Dec"), (1, 12))
        self.assertEqual(parse_ozzy_row_start_hour("19.00 - 20.00"), 19)
        self.assertEqual(parse_ozzy_row_start_hour("16.00-17.00"), 16)


class StateAndFormattingTests(unittest.TestCase):
    def test_filter_future_slots(self) -> None:
        now_bkk = datetime(2026, 11, 24, 20, 15, tzinfo=BANGKOK_TZ)
        slots = [
            CourtSlot(VENUE_COZY, "2026-11-24", 19, "Court 1"),
            CourtSlot(VENUE_COZY, "2026-11-24", 20, "Court 1"),
            CourtSlot(VENUE_COZY, "2026-11-25", 19, "Court 2"),
        ]
        filtered = filter_future_slots(slots, now_bkk, skip_past=True)
        self.assertEqual(len(filtered), 2)
        self.assertEqual([s.date_str for s in filtered], ["2026-11-24", "2026-11-25"])

    def test_state_merge_preserves_failed_venue(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            prev_cozy = CourtSlot(VENUE_COZY, "2026-11-25", 19, "Court 1")
            prev_ozzy = CourtSlot(VENUE_OZZY, "2026-11-25", 20, "Court 3")
            previous = {prev_cozy.key, prev_ozzy.key}

            new_cozy = CourtSlot(VENUE_COZY, "2026-11-25", 20, "Court 1")
            slots_by_venue = {VENUE_COZY: [prev_cozy, new_cozy]}

            saved = merge_and_save_state(
                state_path=state_path,
                previous_keys=previous,
                slots_by_venue=slots_by_venue,
                succeeded_venues={VENUE_COZY},
                updated_at_iso="2026-11-24T18:05:00+07:00",
            )
            loaded = load_state(state_path)
            self.assertEqual(saved, loaded)
            self.assertIn(prev_ozzy.key, loaded)
            self.assertIn(new_cozy.key, loaded)

    def test_format_line_message_consecutive_and_single(self) -> None:
        now_bkk = datetime(2026, 11, 24, 18, 10, tzinfo=BANGKOK_TZ)
        c1_19 = CourtSlot(VENUE_COZY, "2026-11-25", 19, "Court 1")
        c1_20 = CourtSlot(VENUE_COZY, "2026-11-25", 20, "Court 1")
        c2_19 = CourtSlot(VENUE_COZY, "2026-11-25", 19, "Court 2")

        slots_by_venue = {VENUE_COZY: [c1_19, c1_20, c2_19]}
        new_slots = find_new_slots(slots_by_venue, {c1_19.key})

        msg = format_line_message(
            slots_by_venue=slots_by_venue,
            new_slots=new_slots,
            now_bkk=now_bkk,
            target_hours=[19, 20],
        )
        self.assertIsNotNone(msg)
        assert msg is not None
        self.assertIn("ว่างติดกัน 2 ชม. (19:00–21:00): Court 1 🆕", msg)
        self.assertIn("ว่าง 1 ชม. (19:00–20:00): Court 2 🆕", msg)
        self.assertIn("https://book.cozytennis.com/schedule", msg)


if __name__ == "__main__":
    unittest.main()
