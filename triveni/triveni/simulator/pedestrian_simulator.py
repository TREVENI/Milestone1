"""pedestrian_simulator.py – Synthetic pedestrian/localization simulator.

Coordinate system
-----------------
    Origin (0, 0) = intersection center.
    +x = East, +y = North.
    heading_deg: 0° = East, 90° = North, counter-clockwise.

Zones
-----
    entry_zone – where the pedestrian *waits* to cross (curb side).
    exit_zone  – the far side of the crosswalk (destination side).

Uncertainty circle
------------------
    The pedestrian's position is reported as a circle:
        center = (x_m, y_m)
        radius = position_uncertainty_m  (1-sigma estimate)
    The safety engine tests whether this circle overlaps a crosswalk zone.
    A larger uncertainty circle is more likely to touch multiple zones
    → CROSSWALK_AMBIGUOUS.

Named presets and expected decisions
-------------------------------------
    Preset name               | Position        | Notes / expected decision
    ------------------------- | --------------- | -------------------------
    near_correct_crosswalk    | (5.5, 9.5)      | Inside CW_NORTH entry only → WALK (if all else OK)
    near_wrong_crosswalk      | (-9.5, 5.5)     | Inside CW_WEST entry; use with intended="CW_NORTH" → UNAVAILABLE/CROSSWALK_MISMATCH
    between_two_crosswalks    | (8.0, 8.0)      | CW_NORTH entry + CW_EAST exit → UNAVAILABLE/CROSSWALK_AMBIGUOUS
    low_uncertainty           | (5.5, 9.5) 0.3  | CW_NORTH entry, tight circle → WALK (if all else OK)
    high_uncertainty          | (5.5, 9.5) 2.0  | Uncertainty too high → UNAVAILABLE/LOCALIZATION_UNCERTAINTY_TOO_HIGH
    missing_localization      | None            | No localization data → UNAVAILABLE/LOCALIZATION_MISSING
    stale_localization        | (5.5, 9.5)      | Old timestamp → UNAVAILABLE/LOCALIZATION_STALE
    wrong_intersection_id     | (5.5, 9.5)      | Wrong intersection → UNAVAILABLE or FAULT/WRONG_INTERSECTION
    not_in_any_zone           | (0.0, 0.0)      | Center of intersection → UNAVAILABLE/CROSSWALK_NOT_ESTABLISHED

All localization_source values are "SIMULATED" (Milestone 01 requirement).
No wall-clock is used; all timestamps are passed explicitly.
"""
from __future__ import annotations

from typing import Optional

from triveni.models.localization_state import LocalizationState


INTERSECTION_ID = "INT_KEMPS_CORNER"
_DEFAULT_UNCERTAINTY = 0.75


def make_localization(
    x_m: float,
    y_m: float,
    now_ms: int,
    *,
    heading_deg: float = 180.0,
    position_uncertainty_m: float = _DEFAULT_UNCERTAINTY,
    health: str = "OK",
    intersection_id: str = INTERSECTION_ID,
    age_ms: int = 35,               # how old the localization is relative to now_ms
) -> LocalizationState:
    """Build a LocalizationState with explicit timing.

    Parameters
    ----------
    x_m, y_m           : position in meters from intersection center
    now_ms              : current simulated time in ms
    heading_deg         : pedestrian heading (degrees, CCW from East)
    position_uncertainty_m : 1-sigma radius of position estimate
    health              : OK | DEGRADED | FAULT
    intersection_id     : override for wrong-intersection tests
    age_ms              : timestamp_ms = now_ms - age_ms
    """
    return LocalizationState(
        intersection_id=intersection_id,
        x_m=x_m,
        y_m=y_m,
        heading_deg=heading_deg,
        position_uncertainty_m=position_uncertainty_m,
        localization_source="SIMULATED",
        timestamp_ms=now_ms - age_ms,
        health=health,
    )


# ---------------------------------------------------------------------------
# Named presets
# ---------------------------------------------------------------------------

def preset_near_correct_crosswalk(now_ms: int) -> LocalizationState:
    """(5.5, 9.5) – inside CW_NORTH entry zone only.

    Expected: WALK if signal is WALK and all other predicates are satisfied.
    """
    return make_localization(5.5, 9.5, now_ms, heading_deg=180.0)


def preset_near_wrong_crosswalk(now_ms: int) -> LocalizationState:
    """(-9.5, 5.5) – inside CW_WEST entry zone.

    Use with intended_crosswalk_id=\"CW_NORTH\".
    Expected: UNAVAILABLE / CROSSWALK_MISMATCH.
    """
    return make_localization(-9.5, 5.5, now_ms, heading_deg=0.0)


def preset_between_two_crosswalks(now_ms: int) -> LocalizationState:
    """(8.0, 8.0) – CW_NORTH entry zone + CW_EAST exit zone overlap.

    Expected: UNAVAILABLE / CROSSWALK_AMBIGUOUS.
    """
    return make_localization(8.0, 8.0, now_ms)


def preset_low_uncertainty(now_ms: int) -> LocalizationState:
    """(5.5, 9.5) with 0.3 m uncertainty – tight circle in CW_NORTH entry.

    Expected: WALK if signal is WALK and all other predicates are satisfied.
    """
    return make_localization(5.5, 9.5, now_ms, position_uncertainty_m=0.3)


def preset_high_uncertainty(now_ms: int) -> LocalizationState:
    """(5.5, 9.5) with 2.0 m uncertainty – exceeds max_position_uncertainty_m.

    Expected: UNAVAILABLE / LOCALIZATION_UNCERTAINTY_TOO_HIGH.
    """
    return make_localization(5.5, 9.5, now_ms, position_uncertainty_m=2.0)


def preset_missing_localization() -> None:
    """No localization data at all.

    Pass None to the safety engine as the localization argument.
    Expected: UNAVAILABLE / LOCALIZATION_MISSING.
    """
    return None


def preset_stale_localization(now_ms: int, stale_age_ms: int = 900) -> LocalizationState:
    """(5.5, 9.5) with a timestamp that makes the localization stale.

    Expected: UNAVAILABLE / LOCALIZATION_STALE.
    """
    return make_localization(5.5, 9.5, now_ms, age_ms=stale_age_ms)


def preset_wrong_intersection_id(now_ms: int) -> LocalizationState:
    """(5.5, 9.5) but reported for the wrong intersection.

    Expected: UNAVAILABLE (or FAULT) / WRONG_INTERSECTION.
    """
    return make_localization(
        5.5, 9.5, now_ms, intersection_id="INT_WRONG_INTERSECTION"
    )


def preset_not_in_any_zone(now_ms: int) -> LocalizationState:
    """(0.0, 0.0) – intersection center, not in any crosswalk zone.

    Expected: UNAVAILABLE / CROSSWALK_NOT_ESTABLISHED.
    """
    return make_localization(0.0, 0.0, now_ms)
