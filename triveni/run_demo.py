# -*- coding: utf-8 -*-
"""run_demo.py - TRIVENI Core Guidance & Safety Emulator - Live Demos A-E.

Usage:
    python run_demo.py              # all demos in sequence
    python run_demo.py --pause      # pause for Enter between demos (for screen recording)
    python run_demo.py --slow       # add 0.2 s display delay per tick in Demo E (screen recording)

At the end the path to logs/decision_log.jsonl is printed.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Ensure package is importable when run from project root
_PROJECT_ROOT = Path(__file__).parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import yaml

from triveni.models.crosswalk_map import CrosswalkMap
from triveni.models.system_health import SystemHealth
from triveni.safety.safety_engine import evaluate, EvaluationResult
from triveni.logging.event_logger import EventLogger
from triveni.simulator.signal_simulator import (
    make_all_signals, make_stale_signal, four_phase_signals,
)
from triveni.simulator.pedestrian_simulator import (
    make_localization,
    preset_near_correct_crosswalk,
    preset_between_two_crosswalks,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_ROOT = _PROJECT_ROOT
_CONFIG_PATH = _ROOT / "config" / "triveni.yaml"
_MAP_PATH = _ROOT / "data" / "intersection_demo.json"
_LOG_PATH = _ROOT / "logs" / "decision_log.jsonl"

# ---------------------------------------------------------------------------
# Load config and map once at startup
# ---------------------------------------------------------------------------
with open(_CONFIG_PATH, "r", encoding="utf-8") as _f:
    CFG = yaml.safe_load(_f)

CMAP = CrosswalkMap.from_json(_MAP_PATH)

GOOD_HEALTH = SystemHealth(
    edge_service="OK", signal_input="OK", localization_input="OK",
    map_loaded=True, clock_status="OK",
)

LOGGER = EventLogger(_LOG_PATH)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pass_fail(flag: bool) -> str:
    return "[PASS]" if flag else "[FAIL]"


def _sep(char: str = "-", width: int = 68) -> None:
    print(char * width)


def _pause(do_pause: bool) -> None:
    if do_pause:
        input("\n  [Press Enter to continue...]\n")


def _narrate(title: str, story: str, inputs: dict, result: EvaluationResult) -> None:
    """Print the narrated demo output for one scenario."""
    ev = result.evidence
    _sep("=")
    print("  " + title)
    _sep("-")
    print("  " + story)
    _sep("-")
    print("  INPUTS")
    for k, v in inputs.items():
        print("    {}: {}".format(k, v))
    _sep("-")
    print("  PREDICATE CHECKLIST")
    print("    {} Sv  Signal valid and WALK       state={}  age={} ms".format(
        _pass_fail(ev["Sv"]), ev.get("signal_state"), ev.get("signal_age_ms")))
    print("    {} Cv  Crosswalk established       cw={}".format(
        _pass_fail(ev["Cv"]), ev.get("established_crosswalk_id")))
    print("    {} Lv  Localization acceptable     uncertainty={} m  age={} ms".format(
        _pass_fail(ev["Lv"]), ev.get("position_uncertainty_m"), ev.get("localization_age_ms")))
    print("    {} Fv  Information fresh           sig_age={} ms  loc_age={} ms".format(
        _pass_fail(ev["Fv"]), ev.get("signal_age_ms"), ev.get("localization_age_ms")))
    print("    {} Hv  System healthy              signal_src={}  loc={}".format(
        _pass_fail(ev["Hv"]), ev.get("signal_source_health"), ev.get("localization_health")))
    print("    {} Tv  Timing satisfied            remaining={} ms".format(
        _pass_fail(ev["Tv"]), ev.get("remaining_time_ms")))
    _sep("-")
    d = result.decision
    print("  FINAL DECISION: {}  |  reason_codes: {}".format(d.decision, d.reason_codes))
    _sep("=")
    print()


# ---------------------------------------------------------------------------
# Demo A: Valid crossing
# ---------------------------------------------------------------------------

def demo_a(pause: bool) -> None:
    now_ms = 100_000
    signals = make_all_signals(now_ms, states={"CW_NORTH": "WALK"}, remaining_times={"CW_NORTH": 18_000})
    loc = preset_near_correct_crosswalk(now_ms)
    result = evaluate(signals, CMAP, loc, GOOD_HEALTH, now_ms, config=CFG)
    LOGGER.log(result.decision, result.evidence)
    ev = result.evidence
    _narrate(
        title="DEMO A - Valid Crossing",
        story=(
            "A pedestrian stands at the CW_NORTH curb (5.5, 9.5).\n"
            "  The signal is WALK with 18 s remaining. Data is fresh, system healthy.\n"
            "  All six predicates pass -> TRIVENI says WALK."
        ),
        inputs={
            "CW_NORTH signal": "WALK  age={} ms  remaining=18000 ms".format(ev.get("signal_age_ms")),
            "Pedestrian":      "(5.5, 9.5)  uncertainty=0.75 m  zone=CW_NORTH entry",
            "System health":   "ALL OK",
        },
        result=result,
    )
    _pause(pause)


# ---------------------------------------------------------------------------
# Demo B: Ambiguous crosswalk
# ---------------------------------------------------------------------------

def demo_b(pause: bool) -> None:
    now_ms = 101_000
    signals = make_all_signals(now_ms, states={"CW_NORTH": "WALK"}, remaining_times={"CW_NORTH": 18_000})
    loc = preset_between_two_crosswalks(now_ms)   # (8.0, 8.0)
    result = evaluate(signals, CMAP, loc, GOOD_HEALTH, now_ms, config=CFG)
    LOGGER.log(result.decision, result.evidence)
    ev = result.evidence
    _narrate(
        title="DEMO B - Ambiguous Crosswalk",
        story=(
            "A pedestrian stands at (8.0, 8.0) - the NE corner shared by CW_NORTH\n"
            "  entry and CW_EAST exit zones.  TRIVENI cannot determine which crosswalk\n"
            "  is intended -> CROSSWALK_AMBIGUOUS -> UNAVAILABLE."
        ),
        inputs={
            "CW_NORTH signal": "WALK  age={} ms".format(ev.get("signal_age_ms")),
            "Pedestrian":      "(8.0, 8.0)  uncertainty=0.75 m  zone=AMBIGUOUS",
            "System health":   "ALL OK",
        },
        result=result,
    )
    _pause(pause)


# ---------------------------------------------------------------------------
# Demo C: Stale signal
# ---------------------------------------------------------------------------

def demo_c(pause: bool) -> None:
    now_ms = 102_000
    stale = make_stale_signal("CW_NORTH", "WALK", now_ms, stale_age_ms=900, remaining_time_ms=18_000)
    signals = {"CW_NORTH": stale}
    loc = preset_near_correct_crosswalk(now_ms)
    result = evaluate(signals, CMAP, loc, GOOD_HEALTH, now_ms, config=CFG)
    LOGGER.log(result.decision, result.evidence)
    ev = result.evidence
    _narrate(
        title="DEMO C - Stale Signal",
        story=(
            "Signal data from CW_NORTH is 900 ms old - above the 500 ms freshness\n"
            "  threshold.  TRIVENI rejects stale data -> SIGNAL_STALE -> UNAVAILABLE."
        ),
        inputs={
            "CW_NORTH signal": "WALK  age={} ms  (threshold=500 ms)".format(ev.get("signal_age_ms")),
            "Pedestrian":      "(5.5, 9.5)  uncertainty=0.75 m",
            "System health":   "ALL OK",
        },
        result=result,
    )
    _pause(pause)


# ---------------------------------------------------------------------------
# Demo D: DONT_WALK signal
# ---------------------------------------------------------------------------

def demo_d(pause: bool) -> None:
    now_ms = 103_000
    signals = make_all_signals(now_ms, states={"CW_NORTH": "DONT_WALK"})
    loc = preset_near_correct_crosswalk(now_ms)
    result = evaluate(signals, CMAP, loc, GOOD_HEALTH, now_ms, config=CFG)
    LOGGER.log(result.decision, result.evidence)
    ev = result.evidence
    _narrate(
        title="DEMO D - DON'T WALK Signal",
        story=(
            "CW_NORTH signal is DONT_WALK (red man).  Even though the pedestrian's\n"
            "  position, freshness, and health are all valid, the signal predicate Sv\n"
            "  fails -> SIGNAL_NOT_WALK -> WAIT."
        ),
        inputs={
            "CW_NORTH signal": "DONT_WALK  age={} ms".format(ev.get("signal_age_ms")),
            "Pedestrian":      "(5.5, 9.5)  uncertainty=0.75 m",
            "System health":   "ALL OK",
        },
        result=result,
    )
    _pause(pause)


# ---------------------------------------------------------------------------
# Demo E: Journey Replay using four_phase_signals
#
# now_ms: 150000 to 175000 (inclusive, 1000 ms steps)
# Cycle start: 0
#
# Signal timeline (cycle_start=0, t = now_ms % 160000):
#   t=150000 to 159000 -> West-arm vehicles green, DONT_WALK   (Stage 1)
#   t=160000 to 161000 -> Ped interval WALK (30 s left)         (Stage 2)
#   t=162000 onwards   -> Still WALK, ped moves west            (Stage 3)
#   x <= -3 (~172600)  -> Ped enters CW_NORTH exit zone         (Stage 4)
#
# Pedestrian script (spec §12c):
#   Stays at (5.5, 9.5) until 161999, then:
#     x = 5.5 - 0.8 * (now_ms - 162000) / 1000
#     y = 9.5, heading=180, uncertainty=0.75, age=30 ms
#
# NOTE: Mid-crossing guidance is NOT defined in Milestone 01.
# Once the pedestrian leaves the CW_NORTH entry zone (x < 3 approx.) the engine
# outputs UNAVAILABLE / CROSSWALK_NOT_ESTABLISHED.  This is EXPECTED behaviour;
# it is listed under "Known limitations / next milestone" in the README.
# ---------------------------------------------------------------------------
# Demo E: Journey Replay (Commented out for now)
# ---------------------------------------------------------------------------

# def demo_e(pause: bool, slow: bool = False) -> None:
#     """Journey replay: engine called unchanged every 1000 ms, now_ms 150000 to 175000."""
#     _sep("=")
#     print("  DEMO E - JOURNEY REPLAY  (150 000 ms -> 175 000 ms, one tick per 1000 ms)")
#     print("  Signals from four_phase_signals(cycle_start_ms=0)")
#     _sep("=")
# 
#     # Journey parameters
#     START_MS = 150_000
#     END_MS = 175_000
#     PED_MOVE_START_MS = 162_000   # pedestrian starts walking at this ms
#     PED_Y = 9.5
#     PED_SPEED_MPS = 0.8           # m/s westward (decreasing x)
#     UNCERTAINTY = 0.75
# 
#     def _ped_pos(now_ms: int) -> tuple:
#         if now_ms < PED_MOVE_START_MS:
#             return 5.5, PED_Y
#         elapsed_s = (now_ms - PED_MOVE_START_MS) / 1000.0
#         return 5.5 - PED_SPEED_MPS * elapsed_s, PED_Y
# 
#     def _stage(now_ms: int, x: float) -> str:
#         if now_ms <= 159_000:
#             return "Stage 1 - West-arm vehicles green, DONT_WALK, ped waiting"
#         if now_ms <= 161_000:
#             return "Stage 2 - All vehicles red, WALK (30 s remaining), ped at curb"
#         if x > -3.0:
#             return "Stage 3 - Ped walking west (mid-crossing: UNAVAILABLE expected once off entry)"
#         return "Stage 4 - Ped in CW_NORTH exit zone / beyond (UNAVAILABLE expected)"
# 
#     prev_stage = ""
#     tick_count = 0
#     decision_counts: dict = {}
#     false_walks = 0
# 
#     for now_ms in range(START_MS, END_MS + 1, 1000):
#         sigs = four_phase_signals(now_ms, cycle_start_ms=0)
#         x, y = _ped_pos(now_ms)
#         loc = make_localization(x, y, now_ms, age_ms=30, heading_deg=180.0)
#         result = evaluate(sigs, CMAP, loc, GOOD_HEALTH, now_ms, config=CFG)
#         LOGGER.log(result.decision, result.evidence)
# 
#         d = result.decision
#         ev = result.evidence
#         decision_counts[d.decision] = decision_counts.get(d.decision, 0) + 1
#         tick_count += 1
# 
#         if d.decision == "WALK":
#             if not (ev["Sv"] and ev["Cv"] and ev["Lv"] and ev["Fv"] and ev["Hv"] and ev["Tv"]):
#                 false_walks += 1
# 
#         stage = _stage(now_ms, x)
#         if stage != prev_stage:
#             _sep("-")
#             print("  >>  " + stage)
#             _sep("-")
#             prev_stage = stage
# 
#         print(
#             "  t={:7d}  x={:6.2f}  y={:5.2f}  sig={:<10}  rem={:<7}  -> {:<12}  {}".format(
#                 now_ms, x, y,
#                 sigs["CW_NORTH"].signal_state,
#                 str(sigs["CW_NORTH"].remaining_time_ms),
#                 d.decision, d.reason_codes[0],
#             )
#         )
# 
#         if slow:
#             time.sleep(0.2)
# 
#     _sep("=")
#     print("  JOURNEY REPLAY SUMMARY")
#     _sep("-")
#     print("  Total ticks : {}".format(tick_count))
#     for dec, cnt in sorted(decision_counts.items()):
#         print("  {:<12}: {}".format(dec, cnt))
#     print("  False WALK events: {}  <- must be 0".format(false_walks))
#     _sep("=")
#     print()
#     if pause:
#         _pause(pause)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="TRIVENI live demo")
    parser.add_argument("--pause", action="store_true",
                        help="Wait for Enter between demos (for screen recording).")
    parser.add_argument("--slow", action="store_true",
                        help="Add 0.2 s display delay per tick in Demo E (for screen recording).")
    args = parser.parse_args()

    print()
    print("  TRIVENI Core Guidance & Safety Emulator v0.1 - Milestone 01")
    print("  Demos A-D")
    print()

    demo_a(args.pause)
    demo_b(args.pause)
    demo_c(args.pause)
    demo_d(args.pause)
    # demo_e(args.pause, slow=args.slow)  # Demo E commented out for now

    print("  Log written to: {}".format(_LOG_PATH.resolve()))
    print()


if __name__ == "__main__":
    main()
