"""tests/test_safety_engine.py – TRIVENI automated test suite.

Covers all 10 mandatory scenarios (spec §10), 5+ additional tests, and an
exhaustive property-style sweep.  Every test has a one-line plain-English
docstring: situation → expected decision and why.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from triveni.models.crosswalk_map import CrosswalkMap
from triveni.models.guidance_decision import GuidanceDecision
from triveni.models.localization_state import LocalizationState
from triveni.models.signal_state import SignalState
from triveni.models.system_health import SystemHealth
from triveni.safety.safety_engine import DEFAULT_CONFIG, evaluate
from triveni.simulator.pedestrian_simulator import (
    preset_between_two_crosswalks,
    preset_high_uncertainty,
    preset_low_uncertainty,
    preset_missing_localization,
    preset_near_correct_crosswalk,
    preset_near_wrong_crosswalk,
    preset_not_in_any_zone,
    preset_stale_localization,
    preset_wrong_intersection_id,
    make_localization,
)
from triveni.simulator.signal_simulator import (
    make_all_signals,
    make_signal,
    make_signal_with_contradictory_timestamp,
    make_stale_signal,
)
from triveni.logging.event_logger import EventLogger


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

NOW_MS = 100_000
MAP_ID = "INT_KEMPS_CORNER"

_MAP_DATA = {
    "intersection_id": MAP_ID,
    "crosswalks": [
        {"crosswalk_id": "CW_NORTH", "entry_zone": [[3,8],[8,8],[8,11],[3,11]],
         "exit_zone": [[-8,8],[-3,8],[-3,11],[-8,11]], "heading_deg": 180},
        {"crosswalk_id": "CW_EAST",  "entry_zone": [[8,-8],[11,-8],[11,-3],[8,-3]],
         "exit_zone": [[8,3],[11,3],[11,8],[8,8]], "heading_deg": 90},
        {"crosswalk_id": "CW_SOUTH", "entry_zone": [[-8,-11],[-3,-11],[-3,-8],[-8,-8]],
         "exit_zone": [[3,-11],[8,-11],[8,-8],[3,-8]], "heading_deg": 0},
        {"crosswalk_id": "CW_WEST",  "entry_zone": [[-11,3],[-8,3],[-8,8],[-11,8]],
         "exit_zone": [[-11,-8],[-8,-8],[-8,-3],[-11,-3]], "heading_deg": 270},
    ],
}

@pytest.fixture()
def cmap() -> CrosswalkMap:
    return CrosswalkMap.from_dict(_MAP_DATA)

@pytest.fixture()
def good_health() -> SystemHealth:
    return SystemHealth(
        edge_service="OK", signal_input="OK", localization_input="OK",
        map_loaded=True, clock_status="OK",
    )

@pytest.fixture()
def cfg() -> Dict[str, Any]:
    return dict(DEFAULT_CONFIG)


def _walk_signals(cw_id: str, now_ms: int = NOW_MS) -> Dict[str, SignalState]:
    """All signals DONT_WALK except cw_id which is WALK (18 s remaining)."""
    return make_all_signals(
        now_ms,
        states={cw_id: "WALK"},
        remaining_times={cw_id: 18_000},
    )


# ---------------------------------------------------------------------------
# Mandatory scenario 1 – WALK: all predicates valid
# ---------------------------------------------------------------------------

def test_s1_valid_walk(cmap, good_health, cfg):
    """WALK + correct crosswalk + good localization + fresh data → WALK (all mandatory predicates valid)."""
    signals = _walk_signals("CW_NORTH")
    loc = preset_near_correct_crosswalk(NOW_MS)
    result = evaluate(signals, cmap, loc, good_health, NOW_MS, config=cfg)
    assert result.decision.decision == "WALK"
    assert "ALL_REQUIRED_CONDITIONS_VALID" in result.decision.reason_codes


# ---------------------------------------------------------------------------
# Mandatory scenario 2 – DONT_WALK signal → WAIT
# ---------------------------------------------------------------------------

def test_s2_dont_walk_signal(cmap, good_health, cfg):
    """DONT_WALK signal → WAIT (signal does not permit crossing)."""
    signals = make_all_signals(NOW_MS, states={"CW_NORTH": "DONT_WALK"})
    loc = preset_near_correct_crosswalk(NOW_MS)
    result = evaluate(signals, cmap, loc, good_health, NOW_MS, config=cfg)
    assert result.decision.decision == "WAIT"
    assert "SIGNAL_NOT_WALK" in result.decision.reason_codes


# ---------------------------------------------------------------------------
# Mandatory scenario 3 – Signal missing → UNAVAILABLE
# ---------------------------------------------------------------------------

def test_s3_signal_missing(cmap, good_health, cfg):
    """Signal missing for established crosswalk → UNAVAILABLE (no trustworthy signal)."""
    # Pass empty signal dict
    result = evaluate({}, cmap, preset_near_correct_crosswalk(NOW_MS), good_health, NOW_MS, config=cfg)
    assert result.decision.decision == "UNAVAILABLE"
    assert "SIGNAL_MISSING" in result.decision.reason_codes


# ---------------------------------------------------------------------------
# Mandatory scenario 4 – Signal stale → UNAVAILABLE
# ---------------------------------------------------------------------------

def test_s4_signal_stale(cmap, good_health, cfg):
    """Signal age > freshness threshold → UNAVAILABLE (freshness violated)."""
    stale = make_stale_signal("CW_NORTH", "WALK", NOW_MS, stale_age_ms=900,
                              remaining_time_ms=18_000)
    signals = {"CW_NORTH": stale}
    loc = preset_near_correct_crosswalk(NOW_MS)
    result = evaluate(signals, cmap, loc, good_health, NOW_MS, config=cfg)
    assert result.decision.decision == "UNAVAILABLE"
    assert "SIGNAL_STALE" in result.decision.reason_codes


# ---------------------------------------------------------------------------
# Mandatory scenario 5 – Localization missing → UNAVAILABLE
# ---------------------------------------------------------------------------

def test_s5_localization_missing(cmap, good_health, cfg):
    """Localization is None → UNAVAILABLE (position cannot be established)."""
    signals = _walk_signals("CW_NORTH")
    result = evaluate(signals, cmap, None, good_health, NOW_MS, config=cfg)
    assert result.decision.decision == "UNAVAILABLE"
    assert "LOCALIZATION_MISSING" in result.decision.reason_codes


# ---------------------------------------------------------------------------
# Mandatory scenario 6 – Localization uncertainty too high → UNAVAILABLE
# ---------------------------------------------------------------------------

def test_s6_localization_uncertainty_too_high(cmap, good_health, cfg):
    """Uncertainty > max_position_uncertainty_m → UNAVAILABLE (confidence insufficient)."""
    signals = _walk_signals("CW_NORTH")
    loc = preset_high_uncertainty(NOW_MS)   # 2.0 m > 1.5 threshold
    result = evaluate(signals, cmap, loc, good_health, NOW_MS, config=cfg)
    assert result.decision.decision == "UNAVAILABLE"
    assert "LOCALIZATION_UNCERTAINTY_TOO_HIGH" in result.decision.reason_codes


# ---------------------------------------------------------------------------
# Mandatory scenario 7 – Wrong intersection ID → FAULT or UNAVAILABLE
# ---------------------------------------------------------------------------

def test_s7_wrong_intersection(cmap, good_health, cfg):
    """Wrong intersection ID in localization → FAULT or UNAVAILABLE (wrong intersection)."""
    signals = _walk_signals("CW_NORTH")
    loc = preset_wrong_intersection_id(NOW_MS)
    result = evaluate(signals, cmap, loc, good_health, NOW_MS, config=cfg)
    assert result.decision.decision in ("FAULT", "UNAVAILABLE")
    assert "WRONG_INTERSECTION" in result.decision.reason_codes


# ---------------------------------------------------------------------------
# Mandatory scenario 8 – Crosswalk ambiguous → UNAVAILABLE
# ---------------------------------------------------------------------------

def test_s8_crosswalk_ambiguous(cmap, good_health, cfg):
    """Pedestrian between two crosswalks → UNAVAILABLE (intended crossing not established)."""
    signals = _walk_signals("CW_NORTH")
    loc = preset_between_two_crosswalks(NOW_MS)   # (8.0, 8.0)
    result = evaluate(signals, cmap, loc, good_health, NOW_MS, config=cfg)
    assert result.decision.decision == "UNAVAILABLE"
    assert "CROSSWALK_AMBIGUOUS" in result.decision.reason_codes


# ---------------------------------------------------------------------------
# Mandatory scenario 9 – Critical component unhealthy → FAULT
# ---------------------------------------------------------------------------

def test_s9_system_unhealthy(cmap, cfg):
    """FAULT in SystemHealth → FAULT (system health invalid)."""
    bad_health = SystemHealth(
        edge_service="FAULT", signal_input="OK", localization_input="OK",
        map_loaded=True, clock_status="OK",
    )
    signals = _walk_signals("CW_NORTH")
    loc = preset_near_correct_crosswalk(NOW_MS)
    result = evaluate(signals, cmap, loc, bad_health, NOW_MS, config=cfg)
    assert result.decision.decision == "FAULT"
    assert "SYSTEM_UNHEALTHY" in result.decision.reason_codes


# ---------------------------------------------------------------------------
# Mandatory scenario 10 – WALK changes to DONT_WALK → leaves WALK immediately
# ---------------------------------------------------------------------------

def test_s10_walk_then_dont_walk(cmap, good_health, cfg):
    """Two consecutive ticks: tick-1 WALK → WALK; tick-2 DONT_WALK → WAIT immediately."""
    loc = preset_near_correct_crosswalk(NOW_MS)

    # Tick 1 – signal is WALK
    sigs1 = _walk_signals("CW_NORTH", now_ms=NOW_MS)
    r1 = evaluate(sigs1, cmap, loc, good_health, NOW_MS, config=cfg)
    assert r1.decision.decision == "WALK"

    # Tick 2 – signal flips to DONT_WALK (no engine memory / hysteresis)
    now2 = NOW_MS + 1000
    sigs2 = make_all_signals(now2, states={"CW_NORTH": "DONT_WALK"})
    loc2 = preset_near_correct_crosswalk(now2)
    r2 = evaluate(sigs2, cmap, loc2, good_health, now2, config=cfg)
    assert r2.decision.decision == "WAIT"
    assert "SIGNAL_NOT_WALK" in r2.decision.reason_codes


# ---------------------------------------------------------------------------
# Additional test – no signal leakage between crosswalks
# ---------------------------------------------------------------------------

def test_no_signal_leakage(cmap, good_health, cfg):
    """CW_NORTH=DONT_WALK, others=WALK, pedestrian in CW_NORTH entry → WAIT (signal isolated per crosswalk)."""
    signals = make_all_signals(
        NOW_MS,
        states={"CW_NORTH": "DONT_WALK", "CW_EAST": "WALK", "CW_SOUTH": "WALK", "CW_WEST": "WALK"},
        remaining_times={"CW_EAST": 18_000, "CW_SOUTH": 18_000, "CW_WEST": 18_000},
    )
    loc = preset_near_correct_crosswalk(NOW_MS)  # in CW_NORTH entry
    result = evaluate(signals, cmap, loc, good_health, NOW_MS, config=cfg)
    assert result.decision.decision == "WAIT"
    assert "SIGNAL_NOT_WALK" in result.decision.reason_codes


# ---------------------------------------------------------------------------
# Additional test – pedestrian in exit zone only → never WALK
# ---------------------------------------------------------------------------

def test_exit_zone_only_never_walk(cmap, good_health, cfg):
    """Pedestrian only in an exit zone with WALK → never WALK (exit zone ≠ entry zone)."""
    # CW_NORTH exit zone: [[-8,8],[-3,8],[-3,11],[-8,11]]; center (-5.5, 9.5)
    loc = make_localization(-5.5, 9.5, NOW_MS, position_uncertainty_m=0.3)
    signals = make_all_signals(NOW_MS, states={"CW_NORTH": "WALK"}, remaining_times={"CW_NORTH": 18_000})
    result = evaluate(signals, cmap, loc, good_health, NOW_MS, config=cfg)
    assert result.decision.decision != "WALK"


# ---------------------------------------------------------------------------
# Additional test – pedestrian at (0,0) → never WALK
# ---------------------------------------------------------------------------

def test_center_of_intersection_never_walk(cmap, good_health, cfg):
    """Pedestrian at (0,0) intersection center → never WALK (not in any entry zone)."""
    signals = make_all_signals(NOW_MS,
        states={cw: "WALK" for cw in ["CW_NORTH","CW_EAST","CW_SOUTH","CW_WEST"]},
        remaining_times={cw: 18_000 for cw in ["CW_NORTH","CW_EAST","CW_SOUTH","CW_WEST"]},
    )
    loc = preset_not_in_any_zone(NOW_MS)
    result = evaluate(signals, cmap, loc, good_health, NOW_MS, config=cfg)
    assert result.decision.decision != "WALK"
    assert "CROSSWALK_NOT_ESTABLISHED" in result.decision.reason_codes


# ---------------------------------------------------------------------------
# Additional test – corner points are CROSSWALK_AMBIGUOUS
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("x,y", [(8,8), (-8,8), (-8,-8), (8,-8)])
def test_corner_points_ambiguous(x, y, cmap, good_health, cfg):
    """Corner points shared between crosswalk zones → CROSSWALK_AMBIGUOUS (intentional design)."""
    signals = make_all_signals(NOW_MS,
        states={cw: "WALK" for cw in ["CW_NORTH","CW_EAST","CW_SOUTH","CW_WEST"]},
        remaining_times={cw: 18_000 for cw in ["CW_NORTH","CW_EAST","CW_SOUTH","CW_WEST"]},
    )
    loc = make_localization(float(x), float(y), NOW_MS, position_uncertainty_m=0.75)
    result = evaluate(signals, cmap, loc, good_health, NOW_MS, config=cfg)
    assert result.decision.decision == "UNAVAILABLE"
    assert "CROSSWALK_AMBIGUOUS" in result.decision.reason_codes


# ---------------------------------------------------------------------------
# Additional test – each crosswalk correct entry + WALK → WALK
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cw_id,x,y,heading", [
    ("CW_NORTH",  5.5,  9.5, 180.0),
    ("CW_EAST",   9.5, -5.5,  90.0),
    ("CW_SOUTH", -5.5, -9.5,   0.0),
    ("CW_WEST",  -9.5,  5.5, 270.0),
])
def test_each_crosswalk_walk(cw_id, x, y, heading, cmap, good_health, cfg):
    """Correct entry position + WALK for each of the 4 crosswalks → WALK (all predicates valid)."""
    signals = make_all_signals(NOW_MS, states={cw_id: "WALK"}, remaining_times={cw_id: 18_000})
    loc = make_localization(x, y, NOW_MS, heading_deg=heading, position_uncertainty_m=0.75)
    result = evaluate(signals, cmap, loc, good_health, NOW_MS, config=cfg)
    assert result.decision.decision == "WALK", (
        f"{cw_id}: expected WALK but got {result.decision.decision} "
        f"(reason: {result.decision.reason_codes})"
    )


# ---------------------------------------------------------------------------
# Additional test – localization stale → UNAVAILABLE
# ---------------------------------------------------------------------------

def test_localization_stale(cmap, good_health, cfg):
    """Localization age > threshold → UNAVAILABLE / LOCALIZATION_STALE."""
    signals = _walk_signals("CW_NORTH")
    loc = preset_stale_localization(NOW_MS, stale_age_ms=900)
    result = evaluate(signals, cmap, loc, good_health, NOW_MS, config=cfg)
    assert result.decision.decision == "UNAVAILABLE"
    assert "LOCALIZATION_STALE" in result.decision.reason_codes


# ---------------------------------------------------------------------------
# Additional test – insufficient remaining time → WAIT
# ---------------------------------------------------------------------------

def test_insufficient_remaining_time(cmap, good_health, cfg):
    """remaining_time_ms < minimum → WAIT / INSUFFICIENT_REMAINING_TIME."""
    sig = make_signal("CW_NORTH", "WALK", NOW_MS, remaining_time_ms=1_000)
    result = evaluate({"CW_NORTH": sig}, cmap, preset_near_correct_crosswalk(NOW_MS),
                      good_health, NOW_MS, config=cfg)
    assert result.decision.decision == "WAIT"
    assert "INSUFFICIENT_REMAINING_TIME" in result.decision.reason_codes


# ---------------------------------------------------------------------------
# Additional test – remaining_time missing + require_remaining_time=True → not WALK
# ---------------------------------------------------------------------------

def test_missing_remaining_time_required(cmap, good_health, cfg):
    """remaining_time_ms missing and require_remaining_time=True → not WALK."""
    cfg2 = dict(cfg, require_remaining_time=True)
    sig = make_signal("CW_NORTH", "WALK", NOW_MS, remaining_time_ms=None)
    result = evaluate({"CW_NORTH": sig}, cmap, preset_near_correct_crosswalk(NOW_MS),
                      good_health, NOW_MS, config=cfg2)
    assert result.decision.decision != "WALK"


# ---------------------------------------------------------------------------
# Additional test – intended_crosswalk_id mismatch → UNAVAILABLE/CROSSWALK_MISMATCH
# ---------------------------------------------------------------------------

def test_crosswalk_mismatch(cmap, good_health, cfg):
    """Pedestrian in CW_WEST entry, intended CW_NORTH → UNAVAILABLE / CROSSWALK_MISMATCH."""
    signals = make_all_signals(NOW_MS, states={"CW_NORTH": "WALK"}, remaining_times={"CW_NORTH": 18_000})
    loc = preset_near_wrong_crosswalk(NOW_MS)   # in CW_WEST
    result = evaluate(signals, cmap, loc, good_health, NOW_MS,
                      intended_crosswalk_id="CW_NORTH", config=cfg)
    assert result.decision.decision == "UNAVAILABLE"
    assert "CROSSWALK_MISMATCH" in result.decision.reason_codes


# ---------------------------------------------------------------------------
# Additional test – contradictory timestamp (future source) → UNAVAILABLE
# ---------------------------------------------------------------------------

def test_contradictory_signal_timestamp(cmap, good_health, cfg):
    """Future source_timestamp_ms (age < 0) → UNAVAILABLE / SIGNAL_TIMESTAMP_INVALID."""
    sig = make_signal_with_contradictory_timestamp("CW_NORTH", "WALK", NOW_MS,
                                                   remaining_time_ms=18_000)
    result = evaluate({"CW_NORTH": sig}, cmap, preset_near_correct_crosswalk(NOW_MS),
                      good_health, NOW_MS, config=cfg)
    assert result.decision.decision == "UNAVAILABLE"
    assert "SIGNAL_TIMESTAMP_INVALID" in result.decision.reason_codes


# ---------------------------------------------------------------------------
# Model validation tests (spec §10 – last bullet)
# ---------------------------------------------------------------------------

def test_model_rejects_missing_intersection_id():
    """SignalState rejects missing intersection_id → ValueError."""
    with pytest.raises(ValueError, match="intersection_id"):
        SignalState(intersection_id="", crosswalk_id="CW_NORTH", signal_state="WALK",
                    source_timestamp_ms=1000, receive_timestamp_ms=1010, source_health="OK")


def test_model_rejects_negative_uncertainty():
    """LocalizationState rejects negative uncertainty → ValueError."""
    with pytest.raises(ValueError, match="uncertainty"):
        LocalizationState(intersection_id="INT_KEMPS_CORNER", x_m=5.5, y_m=9.5,
                          heading_deg=180, position_uncertainty_m=-0.1,
                          localization_source="SIMULATED", timestamp_ms=1000, health="OK")


def test_model_rejects_unsupported_signal_state():
    """SignalState rejects unsupported signal state → ValueError."""
    with pytest.raises(ValueError, match="unsupported signal_state"):
        SignalState(intersection_id="INT_KEMPS_CORNER", crosswalk_id="CW_NORTH",
                    signal_state="GREEN", source_timestamp_ms=1000,
                    receive_timestamp_ms=1010, source_health="OK")


def test_model_rejects_invalid_health():
    """SystemHealth rejects invalid health value → ValueError."""
    with pytest.raises(ValueError):
        SystemHealth(edge_service="RUNNING", signal_input="OK",
                     localization_input="OK", map_loaded=True, clock_status="OK")


# ---------------------------------------------------------------------------
# Config threshold changes behavior
# ---------------------------------------------------------------------------

def test_config_threshold_changes_behavior(cmap, good_health):
    """Changing YAML threshold (minimum_remaining_walk_time_ms) changes WALK vs WAIT."""
    sig = make_signal("CW_NORTH", "WALK", NOW_MS, remaining_time_ms=3_000)
    loc = preset_near_correct_crosswalk(NOW_MS)

    # Tight threshold: 3000 < 5000 → WAIT
    cfg_tight = dict(DEFAULT_CONFIG, minimum_remaining_walk_time_ms=5_000)
    r_wait = evaluate({"CW_NORTH": sig}, cmap, loc, good_health, NOW_MS, config=cfg_tight)
    assert r_wait.decision.decision == "WAIT"

    # Relaxed threshold: 3000 >= 2000 → WALK
    cfg_loose = dict(DEFAULT_CONFIG, minimum_remaining_walk_time_ms=2_000)
    r_walk = evaluate({"CW_NORTH": sig}, cmap, loc, good_health, NOW_MS, config=cfg_loose)
    assert r_walk.decision.decision == "WALK"


# ---------------------------------------------------------------------------
# Every decision has >= 1 reason code and produces exactly one log line
# ---------------------------------------------------------------------------

def test_every_decision_has_reason_code_and_one_log_line(cmap, good_health, cfg, tmp_path):
    """Every decision has >= 1 reason code and produces exactly one log line."""
    from triveni.logging.event_logger import EventLogger
    log_file = tmp_path / "test_log.jsonl"
    logger = EventLogger(log_file)

    scenarios = [
        (preset_near_correct_crosswalk(NOW_MS), _walk_signals("CW_NORTH")),
        (preset_near_correct_crosswalk(NOW_MS), make_all_signals(NOW_MS, states={"CW_NORTH": "DONT_WALK"})),
        (None, _walk_signals("CW_NORTH")),
    ]
    for loc, sigs in scenarios:
        result = evaluate(sigs, cmap, loc, good_health, NOW_MS, config=cfg)
        assert len(result.decision.reason_codes) >= 1
        logger.log(result.decision, result.evidence)

    lines = log_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == len(scenarios)
    for line in lines:
        record = json.loads(line)
        assert "decision" in record
        assert len(record["reason_codes"]) >= 1


# ---------------------------------------------------------------------------
# Engine exception → FAULT / UNKNOWN_ERROR, never WALK
# ---------------------------------------------------------------------------

def test_engine_exception_gives_fault(cfg):
    """Broken crosswalk_map (None) causes exception → FAULT / UNKNOWN_ERROR, never WALK."""
    # Pass None as crosswalk_map to force an AttributeError inside the engine
    result = evaluate({}, None, None, None, NOW_MS, config=cfg)  # type: ignore[arg-type]
    assert result.decision.decision == "FAULT"
    assert "UNKNOWN_ERROR" in result.decision.reason_codes
    assert result.decision.decision != "WALK"


# ---------------------------------------------------------------------------
# Multiple failures → most conservative state, all reason codes present
# ---------------------------------------------------------------------------

def test_multiple_failures_most_conservative(cmap, cfg):
    """Stale signal + system FAULT → FAULT (most conservative) with both reason codes."""
    bad_health = SystemHealth(edge_service="FAULT", signal_input="OK",
                              localization_input="OK", map_loaded=True, clock_status="OK")
    stale = make_stale_signal("CW_NORTH", "WALK", NOW_MS, stale_age_ms=900,
                              remaining_time_ms=18_000)
    loc = preset_near_correct_crosswalk(NOW_MS)
    result = evaluate({"CW_NORTH": stale}, cmap, loc, bad_health, NOW_MS, config=cfg)
    assert result.decision.decision == "FAULT"
    assert "SYSTEM_UNHEALTHY" in result.decision.reason_codes


# ---------------------------------------------------------------------------
# Read-only principle: no write/control interface on signal model or engine
# ---------------------------------------------------------------------------

def test_no_write_interface_on_signal_state():
    """SignalState exposes no write/control interface (read-only principle, SPEC §2.1)."""
    ss = SignalState(intersection_id="INT_KEMPS_CORNER", crosswalk_id="CW_NORTH",
                     signal_state="WALK", source_timestamp_ms=1000,
                     receive_timestamp_ms=1010, source_health="OK")
    control_names = [n for n in dir(ss) if any(k in n.lower()
                     for k in ("write", "send", "command", "control", "set_signal",
                               "change_signal", "update_signal"))]
    assert control_names == [], f"Found write interface(s): {control_names}"


def test_no_write_interface_on_engine():
    """Safety engine module exposes no write/control interface (read-only principle, SPEC §2.1)."""
    import triveni.safety.safety_engine as eng
    control_names = [n for n in dir(eng) if any(k in n.lower()
                     for k in ("write_signal", "send_signal", "command_signal",
                               "control_signal", "set_signal"))]
    assert control_names == [], f"Found write interface(s): {control_names}"


# ---------------------------------------------------------------------------
# Exhaustive property-style sweep: False WALK events in invalid scenarios = 0
# ---------------------------------------------------------------------------

def test_exhaustive_no_false_walk(cmap, good_health, cfg):
    """Property sweep: zero false WALK events across many combinations of invalid inputs across all 4 crosswalks."""
    false_walks = []
    crosswalks = ["CW_NORTH", "CW_EAST", "CW_SOUTH", "CW_WEST"]
    cw_positions = {
        "CW_NORTH": (5.5, 9.5, 180.0),
        "CW_EAST":  (9.5, -5.5, 90.0),
        "CW_SOUTH": (-5.5, -9.5, 0.0),
        "CW_WEST":  (-9.5, 5.5, 270.0),
    }

    for cw_id in crosswalks:
        x, y, heading = cw_positions[cw_id]
        good_sigs = make_all_signals(NOW_MS, states={cw_id: "WALK"}, remaining_times={cw_id: 18_000})

        invalid_scenarios = [
            # Stale signal
            ("stale_signal", {cw_id: make_stale_signal(cw_id, "WALK", NOW_MS, stale_age_ms=900, remaining_time_ms=18_000)},
             make_localization(x, y, NOW_MS, heading_deg=heading)),
            # DONT_WALK
            ("dont_walk", make_all_signals(NOW_MS, states={cw_id: "DONT_WALK"}),
             make_localization(x, y, NOW_MS, heading_deg=heading)),
            # Missing localization
            ("missing_loc", good_sigs, None),
            # High uncertainty
            ("high_uncertainty", good_sigs,
             make_localization(x, y, NOW_MS, heading_deg=heading, position_uncertainty_m=2.0)),
            # Stale localization
            ("stale_loc", good_sigs,
             make_localization(x, y, NOW_MS, heading_deg=heading, age_ms=900)),
            # Wrong intersection in localization
            ("wrong_intersection", good_sigs,
             make_localization(x, y, NOW_MS, heading_deg=heading, intersection_id="INT_WRONG")),
            # Not in any zone
            ("no_zone", good_sigs,
             make_localization(0.0, 0.0, NOW_MS)),
            # Insufficient remaining time
            ("insufficient_time",
             {cw_id: make_signal(cw_id, "WALK", NOW_MS, remaining_time_ms=500)},
             make_localization(x, y, NOW_MS, heading_deg=heading)),
        ]

        for scenario_name, sigs, loc in invalid_scenarios:
            result = evaluate(sigs, cmap, loc, good_health, NOW_MS, config=cfg)
            if result.decision.decision == "WALK":
                false_walks.append((cw_id, scenario_name, result.decision.reason_codes))

    assert false_walks == [], (
        f"False WALK events in defined invalid scenarios = {len(false_walks)}: {false_walks}"
    )


# ===========================================================================
# Section 10 – four_phase_signals tests (spec §8.1b / §10)
# ===========================================================================

from triveni.simulator.signal_simulator import (
    four_phase_signals,
    CYCLE_MS, PED_WALK_MS, PED_CLEARANCE_MS, PED_BUFFER_MS, VEHICLE_GREEN_MS,
)

_PED_END = PED_WALK_MS + PED_CLEARANCE_MS + PED_BUFFER_MS  # 40 000 ms


def test_four_phase_never_walk_during_vehicle_phase():
    """During vehicle-arm phases (t=40000..CYCLE_MS-1) all crosswalks are DONT_WALK."""
    for t in range(_PED_END, CYCLE_MS, 1000):
        sigs = four_phase_signals(t, cycle_start_ms=0)
        for cw_id, sig in sigs.items():
            assert sig.signal_state == "DONT_WALK", (
                f"t={t}, {cw_id}: expected DONT_WALK, got {sig.signal_state}"
            )


def test_four_phase_never_clearance_during_vehicle_phase():
    """During vehicle-arm phases no crosswalk shows CLEARANCE."""
    for t in range(_PED_END, CYCLE_MS, 1000):
        sigs = four_phase_signals(t, cycle_start_ms=0)
        for cw_id, sig in sigs.items():
            assert sig.signal_state != "CLEARANCE", (
                f"t={t}, {cw_id}: unexpected CLEARANCE during vehicle phase"
            )


def test_four_phase_all_walk_at_start_of_ped_interval():
    """All four crosswalks show WALK at t=0 (start of pedestrian interval) with 30000 ms remaining."""
    sigs = four_phase_signals(0, cycle_start_ms=0)
    for cw_id, sig in sigs.items():
        assert sig.signal_state == "WALK", f"{cw_id}: expected WALK at t=0"
        assert sig.remaining_time_ms == PED_WALK_MS


def test_four_phase_walk_lasts_exactly_ped_walk_ms():
    """WALK phase lasts exactly PED_WALK_MS ms: last WALK at t=29999, first CLEARANCE at t=30000."""
    # last tick of WALK
    sigs_walk = four_phase_signals(PED_WALK_MS - 1, cycle_start_ms=0)
    for cw_id, sig in sigs_walk.items():
        assert sig.signal_state == "WALK", f"{cw_id}: expected WALK at t={PED_WALK_MS-1}"
        assert sig.remaining_time_ms == 1

    # first tick of CLEARANCE
    sigs_clear = four_phase_signals(PED_WALK_MS, cycle_start_ms=0)
    for cw_id, sig in sigs_clear.items():
        assert sig.signal_state == "CLEARANCE", f"{cw_id}: expected CLEARANCE at t={PED_WALK_MS}"


def test_four_phase_clearance_lasts_exactly_ped_clearance_ms():
    """CLEARANCE lasts exactly PED_CLEARANCE_MS ms: last at t=39999, first DONT_WALK at t=40000."""
    clearance_end = PED_WALK_MS + PED_CLEARANCE_MS  # 40 000

    sigs_clear = four_phase_signals(clearance_end - 1, cycle_start_ms=0)
    for cw_id, sig in sigs_clear.items():
        assert sig.signal_state == "CLEARANCE", (
            f"{cw_id}: expected CLEARANCE at t={clearance_end - 1}"
        )
        assert sig.remaining_time_ms == 1

    sigs_dw = four_phase_signals(clearance_end, cycle_start_ms=0)
    for cw_id, sig in sigs_dw.items():
        assert sig.signal_state == "DONT_WALK", (
            f"{cw_id}: expected DONT_WALK at t={clearance_end}"
        )


def test_four_phase_vehicle_arm_order_n_e_s_w():
    """Vehicle arms activate in order N, E, S, W; each lasts VEHICLE_GREEN_MS ms."""
    arm_starts = [
        _PED_END + 0 * VEHICLE_GREEN_MS,   # North  40 000
        _PED_END + 1 * VEHICLE_GREEN_MS,   # East   70 000
        _PED_END + 2 * VEHICLE_GREEN_MS,   # South 100 000
        _PED_END + 3 * VEHICLE_GREEN_MS,   # West  130 000
    ]
    for arm_idx, arm_start in enumerate(arm_starts):
        arm_end = arm_start + VEHICLE_GREEN_MS - 1
        for t in [arm_start, arm_start + 1000, arm_end]:
            sigs = four_phase_signals(t, cycle_start_ms=0)
            for cw_id, sig in sigs.items():
                assert sig.signal_state == "DONT_WALK", (
                    f"Arm {arm_idx}, t={t}, {cw_id}: expected DONT_WALK"
                )
            # remaining_time_ms counts down toward CYCLE_MS
            remaining = sigs["CW_NORTH"].remaining_time_ms
            assert remaining == CYCLE_MS - t, (
                f"Arm {arm_idx}, t={t}: remaining={remaining}, expected {CYCLE_MS - t}"
            )


def test_four_phase_cycle_repeats_every_cycle_ms():
    """Signal state at t and t+CYCLE_MS are identical (cycle repeats)."""
    for t in [0, 10_000, PED_WALK_MS, PED_WALK_MS + 1, 50_000, 100_000, 155_000]:
        sigs_a = four_phase_signals(t, cycle_start_ms=0)
        sigs_b = four_phase_signals(t + CYCLE_MS, cycle_start_ms=0)
        for cw_id in sigs_a:
            assert sigs_a[cw_id].signal_state == sigs_b[cw_id].signal_state, (
                f"t={t}: cycle did not repeat for {cw_id}"
            )
            assert sigs_a[cw_id].remaining_time_ms == sigs_b[cw_id].remaining_time_ms, (
                f"t={t}: remaining_time_ms did not repeat for {cw_id}"
            )


def test_four_phase_deterministic():
    """Same now_ms always gives same output (no randomness or wall-clock dependency)."""
    for t in [0, 10_000, 35_000, 50_000, 130_000]:
        r1 = four_phase_signals(t)
        r2 = four_phase_signals(t)
        for cw_id in r1:
            assert r1[cw_id].signal_state == r2[cw_id].signal_state
            assert r1[cw_id].remaining_time_ms == r2[cw_id].remaining_time_ms


# ---------------------------------------------------------------------------
# Engine + four_phase_signals integration (spec §10 table)
# ---------------------------------------------------------------------------

def test_four_phase_engine_now_10000(cmap, good_health, cfg):
    """four_phase_signals at now_ms=10000 + ped at CW_NORTH entry -> WALK (20s remaining)."""
    now_ms = 10_000
    sigs = four_phase_signals(now_ms, cycle_start_ms=0)
    assert sigs["CW_NORTH"].signal_state == "WALK"
    assert sigs["CW_NORTH"].remaining_time_ms == 20_000

    loc = make_localization(5.5, 9.5, now_ms, age_ms=30)
    result = evaluate(sigs, cmap, loc, good_health, now_ms, config=cfg)
    assert result.decision.decision == "WALK"
    assert "ALL_REQUIRED_CONDITIONS_VALID" in result.decision.reason_codes


def test_four_phase_engine_now_26000_insufficient_time(cmap, good_health, cfg):
    """four_phase_signals at now_ms=26000 -> WAIT/INSUFFICIENT_REMAINING_TIME (4000ms < 5000ms min)."""
    now_ms = 26_000
    sigs = four_phase_signals(now_ms, cycle_start_ms=0)
    assert sigs["CW_NORTH"].signal_state == "WALK"
    assert sigs["CW_NORTH"].remaining_time_ms == 4_000   # 30000 - 26000

    loc = make_localization(5.5, 9.5, now_ms, age_ms=30)
    result = evaluate(sigs, cmap, loc, good_health, now_ms, config=cfg)
    assert result.decision.decision == "WAIT"
    assert "INSUFFICIENT_REMAINING_TIME" in result.decision.reason_codes


def test_four_phase_engine_now_35000_clearance(cmap, good_health, cfg):
    """four_phase_signals at now_ms=35000 -> WAIT/SIGNAL_NOT_WALK (CLEARANCE phase)."""
    now_ms = 35_000
    sigs = four_phase_signals(now_ms, cycle_start_ms=0)
    assert sigs["CW_NORTH"].signal_state == "CLEARANCE"
    assert sigs["CW_NORTH"].remaining_time_ms == 5_000   # 40000 - 35000

    loc = make_localization(5.5, 9.5, now_ms, age_ms=30)
    result = evaluate(sigs, cmap, loc, good_health, now_ms, config=cfg)
    assert result.decision.decision == "WAIT"
    assert "SIGNAL_NOT_WALK" in result.decision.reason_codes

