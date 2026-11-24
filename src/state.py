"""State persistence for deduplicating court availability notifications."""

from __future__ import annotations

import json
from pathlib import Path

from src.models import CourtSlot


def load_state(state_path: Path) -> set[str]:
    """Load previously seen available slot keys from JSON state file."""
    if not state_path.exists():
        return set()
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        keys = data.get("known_available", [])
        return {str(k) for k in keys}
    except (json.JSONDecodeError, OSError, TypeError):
        return set()


def merge_and_save_state(
    state_path: Path,
    previous_keys: set[str],
    slots_by_venue: dict[str, list[CourtSlot]],
    succeeded_venues: set[str],
    updated_at_iso: str,
) -> set[str]:
    """Update state for succeeded venues while preserving prior keys for failed venues."""
    # Keep previous keys only for venues that failed this run so transient errors do not re-trigger spam.
    retained_keys = {
        key
        for key in previous_keys
        if key.split("|", 1)[0] not in succeeded_venues
    }

    current_keys: set[str] = set(retained_keys)
    for venue in succeeded_venues:
        for slot in slots_by_venue.get(venue, []):
            current_keys.add(slot.key)

    payload = {
        "updated_at": updated_at_iso,
        "known_available": sorted(current_keys),
    }
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return current_keys


def find_new_slots(
    slots_by_venue: dict[str, list[CourtSlot]],
    previous_keys: set[str],
) -> list[CourtSlot]:
    """Return slots that were not present in the previous saved state."""
    new_slots: list[CourtSlot] = []
    for slots in slots_by_venue.values():
        for slot in slots:
            if slot.key not in previous_keys:
                new_slots.append(slot)
    return sorted(new_slots)
