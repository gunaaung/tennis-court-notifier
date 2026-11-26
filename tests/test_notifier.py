"""Unit tests for court availability parsing, state deduplication, and formatting."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from src.beat_notify import parse_slots_from_args
from scripts.suanluang_stats import (
    detect_release_events,
    extract_window_config,
    summarize_tennis_day,
)
from src.checkers import (
    parse_beat_times_payload,
    parse_cozy_aria_label,
    parse_ozzy_header_day_month,
    parse_ozzy_row_start_hour,
    parse_simoorgh_availability_payload,
    parse_suanluang_availability_payload,
)
from src.formatter import (
    build_line_oa_booking_url,
    format_line_flex_message,
    format_line_message,
)
from src.models import (
    BANGKOK_TZ,
    CourtSlot,
    VENUE_BEAT,
    VENUE_COZY,
    VENUE_OZZY,
    VENUE_SIMOORGH,
    VENUE_SUANLUANG,
    filter_future_slots,
)
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

    def test_parse_beat_times_payload_excludes_kid_courts(self) -> None:
        payload = {
            "status": 1,
            "slots": [
                {
                    "id": 68400,
                    "courts": [
                        {"id": 1, "title": "Tennis Indoor Court 1", "booked": False},
                        {"id": 9, "title": "Tennis Red Clay Court 9 (Kid)", "booked": False},
                        {"id": 2, "title": "Tennis Indoor Court 2", "booked": True},
                    ],
                },
                {
                    "id": 75600,
                    "courts": [{"id": 3, "title": "Tennis Indoor Court 3", "booked": False}],
                },
            ],
        }
        slots = parse_beat_times_payload(payload, "2026-11-24", {18, 19, 20})
        self.assertEqual(
            slots,
            [CourtSlot(VENUE_BEAT, "2026-11-24", 19, "Indoor Court 1")],
        )

    def test_parse_simoorgh_availability_payload(self) -> None:
        payload = [
            {
                "date": "2026-11-25",
                "slots": [
                    {"courtName": "Court2", "slotSeconds": 64800, "available": True},
                    {"courtName": "Court2", "slotSeconds": 68400, "available": False},
                    {"courtName": "Court2", "slotSeconds": 72000, "available": True},
                    {"courtName": "Court1", "slotSeconds": 75600, "available": True},
                ],
            }
        ]
        slots = parse_simoorgh_availability_payload(
            payload, {"2026-11-24", "2026-11-25"}, {18, 19, 20}
        )
        self.assertEqual(
            slots,
            [
                CourtSlot(VENUE_SIMOORGH, "2026-11-25", 18, "Court2"),
                CourtSlot(VENUE_SIMOORGH, "2026-11-25", 20, "Court2"),
            ],
        )

    def test_parse_suanluang_availability_payload_excludes_tennis_board(self) -> None:
        payload = {
            "courts": {
                "cmqugjzsi000c59fgvl2ydfoq": [
                    {"time": "18:00", "state": "available", "priceSatang": 35000},
                    {"time": "19:00", "state": "booked", "priceSatang": 35000},
                ],
                "cmqugobqw001159fgftxnztct": [
                    {"time": "18:00", "state": "available", "priceSatang": 3000},
                ],
            }
        }
        slots = parse_suanluang_availability_payload(
            payload, "2026-11-25", {18, 19, 20}
        )
        self.assertEqual(
            slots,
            [CourtSlot(VENUE_SUANLUANG, "2026-11-25", 18, "Court 1")],
        )


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

    def test_line_oa_booking_url_and_flex_message(self) -> None:
        url = build_line_oa_booking_url(
            "@cozytennis",
            "สวัสดีครับ ขอจองคอร์ทวันพุธที่ 25 พ.ย. (พรุ่งนี้) เวลา 19:00-21:00 น. (Court 2) ครับ",
        )
        self.assertTrue(url.startswith("https://line.me/R/oaMessage/%40cozytennis/?"))
        self.assertLessEqual(len(url), 1000)

        now_bkk = datetime(2026, 11, 24, 18, 20, tzinfo=BANGKOK_TZ)
        slot_ozzy = CourtSlot(VENUE_OZZY, "2026-11-25", 19, "Court 2")
        slots_by_venue = {VENUE_OZZY: [slot_ozzy]}
        flex = format_line_flex_message(
            slots_by_venue=slots_by_venue,
            new_slots=[slot_ozzy],
            now_bkk=now_bkk,
            target_hours=[19, 20],
        )
        self.assertIsNotNone(flex)
        assert flex is not None
        self.assertEqual(flex["type"], "flex")
        self.assertLessEqual(len(flex["altText"]), 400)
        bubble = flex["contents"]
        self.assertEqual(bubble["type"], "bubble")
        buttons = bubble["footer"]["contents"]
        self.assertEqual(len(buttons), 2)
        for btn in buttons:
            self.assertLessEqual(len(btn["action"]["label"]), 40)
            self.assertLessEqual(len(btn["action"]["uri"]), 1000)
        self.assertTrue(
            buttons[0]["action"]["uri"].startswith(
                "https://line.me/R/oaMessage/%40925atqia/?"
            )
        )

    def test_three_hour_window_consecutive_runs(self) -> None:
        now_bkk = datetime(2026, 11, 24, 17, 30, tzinfo=BANGKOK_TZ)
        slots = [
            # Court 1: 3 consecutive hours (18:00-21:00)
            CourtSlot(VENUE_COZY, "2026-11-25", 18, "Court 1"),
            CourtSlot(VENUE_COZY, "2026-11-25", 19, "Court 1"),
            CourtSlot(VENUE_COZY, "2026-11-25", 20, "Court 1"),
            # Court 2: 2 consecutive hours (18:00-20:00)
            CourtSlot(VENUE_COZY, "2026-11-25", 18, "Court 2"),
            CourtSlot(VENUE_COZY, "2026-11-25", 19, "Court 2"),
            # Court 3: split single hours (18:00-19:00 and 20:00-21:00)
            CourtSlot(VENUE_COZY, "2026-11-25", 18, "Court 3"),
            CourtSlot(VENUE_COZY, "2026-11-25", 20, "Court 3"),
        ]
        msg = format_line_message(
            slots_by_venue={VENUE_COZY: slots},
            new_slots=slots,
            now_bkk=now_bkk,
            target_hours=[18, 19, 20],
        )
        self.assertIsNotNone(msg)
        assert msg is not None
        self.assertIn("ว่างติดกัน 3 ชม. (18:00–21:00): Court 1 🆕", msg)
        self.assertIn("ว่างติดกัน 2 ชม. (18:00–20:00): Court 2 🆕", msg)
        self.assertIn("ว่าง 1 ชม. (18:00–19:00): Court 3 🆕", msg)
        self.assertIn("ว่าง 1 ชม. (20:00–21:00): Court 3 🆕", msg)

    def test_beat_notify_parse_slots_excludes_kid(self) -> None:
        slots = parse_slots_from_args(
            [
                "2026-11-24|19|Tennis Indoor Court 1",
                "2026-11-24|19|Tennis Red Clay Court 9 (Kid)",
            ],
            None,
        )
        self.assertEqual(
            slots,
            [CourtSlot(VENUE_BEAT, "2026-11-24", 19, "Indoor Court 1")],
        )

    def test_suanluang_window_config_and_release_detection(self) -> None:
        html = r'\"windowOpenDow\":0,\"windowOpenHour\":20,\"windowMode\":\"WEEK\",\"windowRollingDays\":14'
        cfg = extract_window_config(html)
        self.assertEqual(
            cfg,
            {
                "windowMode": "WEEK",
                "windowOpenDow": 0,
                "windowOpenHour": 20,
                "windowRollingDays": 14,
            },
        )

        day_summary = summarize_tennis_day(
            {
                "courts": {
                    "cmqugjzsi000c59fgvl2ydfoq": [
                        {"time": "18:00", "state": "booked"},
                        {"time": "19:00", "state": "available"},
                    ],
                    "cmqugobqw001159fgftxnztct": [
                        {"time": "18:00", "state": "booked"},
                    ],
                }
            },
            "2026-12-01",
        )
        self.assertEqual(day_summary["booked"], 1)
        self.assertEqual(day_summary["available"], 1)
        self.assertEqual(day_summary["eve_avail"], ["Court 1@19:00"])

        events = detect_release_events(
            previous_days={"2026-12-01": {"booked": 0, "available": 84}},
            current_days=[day_summary],
            today=datetime(2026, 11, 29, 20, 5, tzinfo=BANGKOK_TZ).date(),
            now_iso="2026-11-29T20:05:00+07:00",
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["date"], "2026-12-01")
        self.assertEqual(events[0]["days_ahead"], 2)


if __name__ == "__main__":
    unittest.main()
