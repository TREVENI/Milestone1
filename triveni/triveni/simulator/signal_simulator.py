"""signal_simulator.py - Synthetic traffic-signal simulator.

SPaT (Signal Phase and Timing) Primer
--------------------------------------
SPaT describes *which phase* the pedestrian signal is in right now and
*how long* until it changes.  TRIVENI maps SPaT data to its internal model:

    Physical display                 signal_state field
    -------------------------------- ------------------
    Pedestrian green man (WALK)   -> WALK
    Flashing hand (clearance)     -> CLEARANCE
    Red man (DON'T WALK)          -> DONT_WALK
    Time left in current phase    -> remaining_time_ms
    Time controller produced data -> source_timestamp_ms
    Time TRIVENI received it      -> receive_timestamp_ms

Signal age = now_ms - source_timestamp_ms.
A signal is stale if its age > signal_freshness_ms (config threshold).

Default timestamps used by all builders:
    source_timestamp_ms  = now_ms - 50   (signal was produced 50 ms ago)
    receive_timestamp_ms = now_ms - 10   (TRIVENI received it 10 ms ago)

Only the **pedestrian signal** of each crosswalk is used.
Nothing here is connected to a real signal controller.
WALK alone does NOT mean "cross" - all six safety predicates must hold.

Four-Phase Signal Cycle (four_phase_signals)
--------------------------------------------
One-arm-at-a-time plan: only one vehicle arm moves at a time.
When any vehicle arm is green, all pedestrian crossings show DONT_WALK.
Pedestrian WALK and CLEARANCE are given only while ALL vehicles are red.

CYCLE_MS = PED_WALK_MS + PED_CLEARANCE_MS + PED_BUFFER_MS
         + 4 * VEHICLE_GREEN_MS = 160 000 ms

    t in cycle      Phase                  Pedestrian signal  Vehicle phase
    --------------- ---------------------- -----------------  -----------------
    0 - 29 999      Pedestrian WALK        WALK               All vehicles RED
    30 000 - 39 999 Pedestrian CLEARANCE   CLEARANCE          All vehicles RED
    40 000 - 69 999 North-arm vehicles     DONT_WALK          North GREEN
    70 000 - 99 999 East-arm vehicles      DONT_WALK          East GREEN
    100 000-129 999 South-arm vehicles     DONT_WALK          South GREEN
    130 000-159 999 West-arm vehicles      DONT_WALK          West GREEN

remaining_time_ms:
    WALK      -> ms left in the WALK sub-phase
    CLEARANCE -> ms left in the CLEARANCE sub-phase
    DONT_WALK -> ms until the next WALK phase begins

Examples with cycle_start_ms=0:
    now_ms=10000 -> WALK,      remaining=20000
    now_ms=35000 -> CLEARANCE, remaining=5000
    now_ms=50000 -> DONT_WALK (north arm green), remaining=110000

Vehicle phases appear only in comments/docstrings.
The SignalState model carries only the pedestrian signal.
The safety engine never reads vehicle signals.

All simulators are deterministic: no wall-clock, no time.time(), no sleep,
no threads.  Everything is computed purely from the now_ms argument.
"""
from __future__ import annotations

from typing import Dict, Optional

from triveni.models.signal_state import SignalState


INTERSECTION_ID = "INT_KEMPS_CORNER"
CROSSWALK_IDS = ["CW_NORTH", "CW_EAST", "CW_SOUTH", "CW_WEST"]

# ---------------------------------------------------------------------------
# Four-phase cycle constants (named so tests and demos can reference them)
# ---------------------------------------------------------------------------
VEHICLE_GREEN_MS: int = 30_000   # duration of each vehicle-arm green phase
PED_WALK_MS: int = 30_000        # pedestrian WALK sub-phase duration
PED_CLEARANCE_MS: int = 10_000   # pedestrian CLEARANCE sub-phase duration
PED_BUFFER_MS: int = 0           # optional all-red buffer after CLEARANCE
CYCLE_MS: int = (
    PED_WALK_MS + PED_CLEARANCE_MS + PED_BUFFER_MS + 4 * VEHICLE_GREEN_MS
)  # = 160 000 ms


# ---------------------------------------------------------------------------
# Default timestamp helpers
# ---------------------------------------------------------------------------

def _default_timestamps(now_ms: int) -> tuple[int, int]:
    """Return (source_timestamp_ms, receive_timestamp_ms) defaults."""
    return now_ms - 50, now_ms - 10


# ---------------------------------------------------------------------------
# Single-crosswalk static builders
# ---------------------------------------------------------------------------

def make_signal(
    crosswalk_id: str,
    signal_state: str,
    now_ms: int,
    *,
    remaining_time_ms: Optional[int] = None,
    source_age_ms: int = 50,
    receive_age_ms: int = 10,
    source_health: str = "OK",
    intersection_id: str = INTERSECTION_ID,
) -> SignalState:
    """Build a single SignalState with explicit timing.

    Parameters
    ----------
    crosswalk_id    : target crosswalk
    signal_state    : WALK | DONT_WALK | CLEARANCE (or DON'T_WALK alias)
    now_ms          : current simulated time in ms
    remaining_time_ms : ms left in the current phase (None = omit)
    source_age_ms   : source_timestamp_ms = now_ms - source_age_ms  (default 50)
    receive_age_ms  : receive_timestamp_ms = now_ms - receive_age_ms (default 10)
    source_health   : OK | DEGRADED | FAULT
    intersection_id : override if needed (e.g. wrong intersection tests)
    """
    source_ts = now_ms - source_age_ms
    receive_ts = now_ms - receive_age_ms
    return SignalState(
        intersection_id=intersection_id,
        crosswalk_id=crosswalk_id,
        signal_state=signal_state,
        remaining_time_ms=remaining_time_ms,
        source_timestamp_ms=source_ts,
        receive_timestamp_ms=receive_ts,
        source_health=source_health,
    )


def make_stale_signal(
    crosswalk_id: str,
    signal_state: str,
    now_ms: int,
    stale_age_ms: int = 900,
    *,
    remaining_time_ms: Optional[int] = None,
    source_health: str = "OK",
) -> SignalState:
    """Build a SignalState whose age exceeds the typical freshness threshold."""
    return make_signal(
        crosswalk_id=crosswalk_id,
        signal_state=signal_state,
        now_ms=now_ms,
        remaining_time_ms=remaining_time_ms,
        source_age_ms=stale_age_ms,
        source_health=source_health,
    )


def make_delayed_signal(
    crosswalk_id: str,
    signal_state: str,
    now_ms: int,
    delay_ms: int = 900,
    *,
    remaining_time_ms: Optional[int] = None,
) -> SignalState:
    """Build a SignalState delayed in transit (same effect as stale)."""
    return make_signal(
        crosswalk_id=crosswalk_id,
        signal_state=signal_state,
        now_ms=now_ms,
        remaining_time_ms=remaining_time_ms,
        source_age_ms=delay_ms,
    )


def make_signal_with_contradictory_timestamp(
    crosswalk_id: str,
    signal_state: str,
    now_ms: int,
    *,
    remaining_time_ms: Optional[int] = None,
) -> SignalState:
    """Build a SignalState where source_timestamp is in the future (contradictory).

    Produces age < 0, detected as SIGNAL_TIMESTAMP_INVALID by the engine.
    """
    future_source_ts = now_ms + 5_000
    receive_ts = future_source_ts + 10
    return SignalState(
        intersection_id=INTERSECTION_ID,
        crosswalk_id=crosswalk_id,
        signal_state=signal_state,
        remaining_time_ms=remaining_time_ms,
        source_timestamp_ms=future_source_ts,
        receive_timestamp_ms=receive_ts,
        source_health="OK",
    )


# ---------------------------------------------------------------------------
# Full-intersection static helper
# ---------------------------------------------------------------------------

def make_all_signals(
    now_ms: int,
    states: Optional[Dict[str, str]] = None,
    remaining_times: Optional[Dict[str, int]] = None,
    source_age_ms: int = 50,
) -> Dict[str, SignalState]:
    """Build a dict of SignalState for all four crosswalks.

    Parameters
    ----------
    now_ms          : current simulated time
    states          : mapping crosswalk_id -> signal_state.
                      Defaults to DONT_WALK for any crosswalk not listed.
    remaining_times : mapping crosswalk_id -> remaining_time_ms (optional per crosswalk)
    source_age_ms   : age applied to all signals
    """
    states = states or {}
    remaining_times = remaining_times or {}
    result: Dict[str, SignalState] = {}
    for cw_id in CROSSWALK_IDS:
        state = states.get(cw_id, "DONT_WALK")
        result[cw_id] = make_signal(
            crosswalk_id=cw_id,
            signal_state=state,
            now_ms=now_ms,
            remaining_time_ms=remaining_times.get(cw_id),
            source_age_ms=source_age_ms,
        )
    return result


# ---------------------------------------------------------------------------
# Four-phase coordinated signal simulation
# ---------------------------------------------------------------------------

def four_phase_signals(
    now_ms: int,
    cycle_start_ms: int = 0,
) -> Dict[str, SignalState]:
    """Return all four per-crosswalk SignalStates for one tick of the four-phase cycle.

    The cycle is deterministic and stateless: same now_ms always gives the same output.
    No wall-clock, no time.time(), no sleep, no threads.

    Cycle structure (see module docstring for the full table):
        Phase 1 - Pedestrian WALK      (0 to PED_WALK_MS - 1)
        Phase 2 - Pedestrian CLEARANCE (PED_WALK_MS to PED_WALK_MS+PED_CLEARANCE_MS-1)
        Phase 3 - Pedestrian BUFFER    (if PED_BUFFER_MS > 0; default 0)
        Phase 4 - North arm green      (VEHICLE_GREEN_MS)
        Phase 5 - East arm green       (VEHICLE_GREEN_MS)
        Phase 6 - South arm green      (VEHICLE_GREEN_MS)
        Phase 7 - West arm green       (VEHICLE_GREEN_MS)

    Parameters
    ----------
    now_ms          : current simulated time in ms
    cycle_start_ms  : when the current cycle started (default 0)

    Returns
    -------
    Dict mapping crosswalk_id -> SignalState for all four crosswalks.
    """
    # Position within the current cycle
    t = (now_ms - cycle_start_ms) % CYCLE_MS

    # Phase boundaries
    _walk_end = PED_WALK_MS                                    # 30 000
    _clear_end = _walk_end + PED_CLEARANCE_MS                  # 40 000
    _buffer_end = _clear_end + PED_BUFFER_MS                   # 40 000 (buffer=0)
    # Vehicle arms: N then E then S then W
    _n_end = _buffer_end + VEHICLE_GREEN_MS                    # 70 000
    _e_end = _n_end + VEHICLE_GREEN_MS                         # 100 000
    _s_end = _e_end + VEHICLE_GREEN_MS                         # 130 000
    # _w_end = _s_end + VEHICLE_GREEN_MS = CYCLE_MS            # 160 000

    # Determine pedestrian signal state and remaining_time_ms
    if t < _walk_end:
        # Pedestrian WALK - all vehicles RED
        state = "WALK"
        remaining = _walk_end - t                              # ms left in WALK

    elif t < _clear_end:
        # Pedestrian CLEARANCE - all vehicles still RED
        state = "CLEARANCE"
        remaining = _clear_end - t                             # ms left in CLEARANCE

    elif t < _buffer_end:
        # Pedestrian BUFFER (all-red; DONT_WALK) - only active if PED_BUFFER_MS > 0
        state = "DONT_WALK"
        remaining = CYCLE_MS - t                               # ms until next WALK

    else:
        # Vehicle phase: N, E, S, or W arm green - pedestrian DONT_WALK
        # (Vehicle phases are named in comments only; engine never reads them)
        state = "DONT_WALK"
        remaining = CYCLE_MS - t                               # ms until next WALK

    src_ts = now_ms - 50
    receive_ts = now_ms - 10

    result: Dict[str, SignalState] = {}
    for cw_id in CROSSWALK_IDS:
        result[cw_id] = SignalState(
            intersection_id=INTERSECTION_ID,
            crosswalk_id=cw_id,
            signal_state=state,
            remaining_time_ms=remaining,
            source_timestamp_ms=src_ts,
            receive_timestamp_ms=receive_ts,
            source_health="OK",
        )
    return result
