"""safety_engine.py – TRIVENI Core Safety Engine.

Responsibility
--------------
Answer exactly one question per tick:
    "Given signal state, crosswalk information, pedestrian position/confidence,
     timing, and system health – what guidance should TRIVENI produce?"

Output is exactly ONE of: WALK | WAIT | UNAVAILABLE | FAULT
plus one or more reason codes, captured in an EvaluationResult.

Six Safety Predicates (all must hold for WALK)
----------------------------------------------
    Sv  Signal is valid and is WALK.
        Check: signal_state == "WALK" for the established crosswalk.
        Fail → WAIT / SIGNAL_NOT_WALK.

    Cv  Crosswalk identity is established.
        Check: the pedestrian's uncertainty circle overlaps exactly one
               crosswalk's ENTRY zone (and no other crosswalk's ENTRY zone).
        Fail → UNAVAILABLE / CROSSWALK_AMBIGUOUS or CROSSWALK_NOT_ESTABLISHED.

    Lv  Localization is acceptable.
        Check: present, same intersection, uncertainty <= max threshold.
        Fail → UNAVAILABLE / LOCALIZATION_MISSING, WRONG_INTERSECTION,
                             LOCALIZATION_UNCERTAINTY_TOO_HIGH.

    Fv  Required information is fresh.
        Check: signal age and localization age are within freshness thresholds.
               Contradictory timestamps (age < 0) are also caught here.
        Fail → UNAVAILABLE / SIGNAL_STALE, SIGNAL_TIMESTAMP_INVALID,
                             LOCALIZATION_STALE, LOCALIZATION_TIMESTAMP_INVALID.

    Hv  System is healthy.
        Check: no FAULT in SystemHealth fields, signal.source_health,
               localization.health, or map_loaded flag.
        Fail → FAULT / SYSTEM_UNHEALTHY (any FAULT),
                UNAVAILABLE / SYSTEM_DEGRADED (DEGRADED, no FAULT).

    Tv  Temporal constraints are satisfied.
        Check: remaining_time_ms >= minimum_remaining_walk_time_ms.
               If require_remaining_time is true and remaining_time_ms is
               missing, WALK is not allowed.
        Fail → WAIT / INSUFFICIENT_REMAINING_TIME.

Check order (fixed; spec §7)
-----------------------------
    1  intersection identity   (Lv / Sv partial)
    2  crosswalk identity      (Cv)
    3  signal state            (Sv)
    4  signal freshness        (Fv)
    5  localization freshness  (Fv)
    6  localization uncertainty(Lv)
    7  system health           (Hv)
    8  timing constraints      (Tv)
    9  produce guidance state
    10 produce reason codes

Decision priority (most conservative wins)
------------------------------------------
    FAULT > UNAVAILABLE > WAIT > WALK

The engine is pure and deterministic: function of inputs + config only.
No wall-clock access, no hidden state, no side effects.
Any uncaught exception → FAULT / UNKNOWN_ERROR (never WALK).

SAFETY RULE: the software must never produce WALK if any mandatory safety
predicate is invalid.  Any exception or unknown state gives a non-WALK result.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from triveni.models.crosswalk_map import CrosswalkMap
from triveni.models.guidance_decision import GuidanceDecision
from triveni.models.localization_state import LocalizationState
from triveni.models.signal_state import SignalState
from triveni.models.system_health import SystemHealth


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class EvaluationResult:
    """Output of one safety-engine evaluation tick.

    Attributes
    ----------
    decision : GuidanceDecision
        The single guidance output.
    evidence : dict
        All predicate results, ages, candidate crosswalks, thresholds used –
        everything the logger needs to reconstruct the decision.
    """
    decision: GuidanceDecision
    evidence: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Decision priority helpers
# ---------------------------------------------------------------------------

_PRIORITY = {"FAULT": 3, "UNAVAILABLE": 2, "WAIT": 1, "WALK": 0}


def _more_conservative(a: str, b: str) -> str:
    """Return the more conservative of two decision strings."""
    return a if _PRIORITY[a] >= _PRIORITY[b] else b


# ---------------------------------------------------------------------------
# Default config (used when no config dict is passed)
# ---------------------------------------------------------------------------

DEFAULT_CONFIG: Dict[str, Any] = {
    "signal_freshness_ms": 500,
    "localization_freshness_ms": 500,
    "max_position_uncertainty_m": 1.5,
    "minimum_remaining_walk_time_ms": 5000,
    "wrong_intersection_result": "UNAVAILABLE",
    "require_remaining_time": True,
}


# ---------------------------------------------------------------------------
# Safety engine
# ---------------------------------------------------------------------------

def evaluate(
    signals: Union[List[SignalState], Dict[str, SignalState], None],
    crosswalk_map: CrosswalkMap,
    localization: Optional[LocalizationState],
    health: Optional[SystemHealth],
    now_ms: int,
    intended_crosswalk_id: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> EvaluationResult:
    """Evaluate one tick and return a GuidanceDecision + evidence dict.

    Parameters
    ----------
    signals             : all SignalStates for this intersection (list or
                          dict keyed by crosswalk_id).  May be None/empty.
    crosswalk_map       : loaded CrosswalkMap for the intersection.
    localization        : pedestrian LocalizationState, or None if missing.
    health              : SystemHealth snapshot, or None if missing.
    now_ms              : current simulated time in ms (no wall-clock).
    intended_crosswalk_id : if given, the crosswalk the pedestrian intends to
                          cross; mismatch with established crosswalk →
                          CROSSWALK_MISMATCH.
    config              : dict of thresholds (loaded from triveni.yaml).
                          Defaults to DEFAULT_CONFIG if not provided.

    Returns
    -------
    EvaluationResult with .decision (GuidanceDecision) and .evidence (dict).
    """
    # Wrap everything: any exception → FAULT / UNKNOWN_ERROR, never WALK.
    try:
        return _evaluate_inner(
            signals, crosswalk_map, localization, health,
            now_ms, intended_crosswalk_id, config or DEFAULT_CONFIG
        )
    except Exception as exc:  # noqa: BLE001
        gd = GuidanceDecision(
            decision="FAULT",
            reason_codes=["UNKNOWN_ERROR"],
            intersection_id=getattr(crosswalk_map, "intersection_id", "UNKNOWN"),
            crosswalk_id=None,
            decision_timestamp_ms=now_ms,
        )
        return EvaluationResult(
            decision=gd,
            evidence={"exception": str(exc), "Sv": False, "Cv": False,
                      "Lv": False, "Fv": False, "Hv": False, "Tv": False},
        )


def _evaluate_inner(
    signals: Union[List[SignalState], Dict[str, SignalState], None],
    crosswalk_map: CrosswalkMap,
    localization: Optional[LocalizationState],
    health: Optional[SystemHealth],
    now_ms: int,
    intended_crosswalk_id: Optional[str],
    cfg: Dict[str, Any],
) -> EvaluationResult:
    """Core evaluation logic (called inside try/except in evaluate())."""

    map_id = crosswalk_map.intersection_id

    # Normalise signals to dict
    if signals is None:
        sig_dict: Dict[str, SignalState] = {}
    elif isinstance(signals, list):
        sig_dict = {s.crosswalk_id: s for s in signals}
    else:
        sig_dict = dict(signals)

    # Accumulated failures (we collect all, then pick most conservative)
    failures: List[tuple[str, str]] = []   # (decision, reason_code)

    # Predicate booleans for evidence / logging
    Sv = Cv = Lv = Fv = Hv = Tv = False

    # Established crosswalk (set during Cv check)
    established_cw_id: Optional[str] = None
    candidate_crosswalks: List[tuple[str, str]] = []

    # ----------------------------------------------------------------
    # 1. Intersection identity
    # ----------------------------------------------------------------
    wrong_intersection = False

    if localization is not None and localization.intersection_id != map_id:
        wrong_intersection = True
        wrong_result = cfg.get("wrong_intersection_result", "UNAVAILABLE")
        failures.append((wrong_result, "WRONG_INTERSECTION"))

    # Check signal intersection IDs (only those present in sig_dict)
    for cw_id, sig in sig_dict.items():
        if sig.intersection_id != map_id:
            wrong_intersection = True
            wrong_result = cfg.get("wrong_intersection_result", "UNAVAILABLE")
            failures.append((wrong_result, "WRONG_INTERSECTION"))
            break   # one failure is enough

    # ----------------------------------------------------------------
    # 2. Crosswalk identity  (Cv)
    # ----------------------------------------------------------------
    if localization is not None and not wrong_intersection:
        candidate_crosswalks = crosswalk_map.which_crosswalk_zones_overlap(
            localization.x_m, localization.y_m, localization.position_uncertainty_m
        )

        # Distinct crosswalks (by ENTRY or EXIT) whose zone overlaps the circle.
        # Per spec §7: "more than one crosswalk" → CROSSWALK_AMBIGUOUS.
        distinct_cws_any_zone = list(dict.fromkeys(cw for cw, _ in candidate_crosswalks))

        entry_candidates = [cw for cw, zone in candidate_crosswalks if zone == "entry"]
        unique_entry_cws = list(dict.fromkeys(entry_candidates))  # preserve order, dedup

        if len(distinct_cws_any_zone) > 1:
            # More than one crosswalk (any zone) overlaps → ambiguous
            failures.append(("UNAVAILABLE", "CROSSWALK_AMBIGUOUS"))
        elif len(unique_entry_cws) == 0:
            # No entry zone overlaps (may be in an exit zone only, or nowhere)
            failures.append(("UNAVAILABLE", "CROSSWALK_NOT_ESTABLISHED"))
        else:
            # Exactly one crosswalk appears and it has an entry zone overlap
            established_cw_id = unique_entry_cws[0]
            Cv = True

            # Check intended crosswalk mismatch
            if (
                intended_crosswalk_id is not None
                and intended_crosswalk_id != established_cw_id
            ):
                Cv = False
                established_cw_id = None
                failures.append(("UNAVAILABLE", "CROSSWALK_MISMATCH"))

    # ----------------------------------------------------------------
    # 3. Signal state  (Sv – partial; freshness checked in step 4)
    # ----------------------------------------------------------------
    established_signal: Optional[SignalState] = None

    if Cv and established_cw_id is not None:
        established_signal = sig_dict.get(established_cw_id)
        if established_signal is None:
            failures.append(("UNAVAILABLE", "SIGNAL_MISSING"))
        elif established_signal.signal_state in ("DONT_WALK", "CLEARANCE"):
            failures.append(("WAIT", "SIGNAL_NOT_WALK"))
        elif established_signal.signal_state == "WALK":
            Sv = True   # tentative; freshness check may revoke this

    # ----------------------------------------------------------------
    # 4. Signal freshness  (Fv – signal side)
    # ----------------------------------------------------------------
    signal_age_ms: Optional[int] = None

    if established_signal is not None:
        src_ts = established_signal.source_timestamp_ms
        rcv_ts = established_signal.receive_timestamp_ms
        signal_age_ms = now_ms - src_ts

        if signal_age_ms < 0 or rcv_ts < src_ts:
            Sv = False
            failures.append(("UNAVAILABLE", "SIGNAL_TIMESTAMP_INVALID"))
        elif signal_age_ms > cfg["signal_freshness_ms"]:
            Sv = False
            failures.append(("UNAVAILABLE", "SIGNAL_STALE"))

    # ----------------------------------------------------------------
    # 5. Localization freshness  (Fv – localization side)
    # ----------------------------------------------------------------
    localization_age_ms: Optional[int] = None

    if localization is None:
        failures.append(("UNAVAILABLE", "LOCALIZATION_MISSING"))
    else:
        localization_age_ms = now_ms - localization.timestamp_ms
        if localization_age_ms < 0:
            Lv = False
            failures.append(("UNAVAILABLE", "LOCALIZATION_TIMESTAMP_INVALID"))
        elif localization_age_ms > cfg["localization_freshness_ms"]:
            Lv = False
            failures.append(("UNAVAILABLE", "LOCALIZATION_STALE"))
        else:
            Fv = True   # freshness OK so far; uncertainty checked next

    # ----------------------------------------------------------------
    # 6. Localization uncertainty  (Lv)
    # ----------------------------------------------------------------
    if localization is not None and localization_age_ms is not None and localization_age_ms >= 0:
        if localization.position_uncertainty_m > cfg["max_position_uncertainty_m"]:
            Lv = False
            failures.append(("UNAVAILABLE", "LOCALIZATION_UNCERTAINTY_TOO_HIGH"))
        elif Fv:
            Lv = True

    # ----------------------------------------------------------------
    # 7. System health  (Hv)
    # ----------------------------------------------------------------
    any_fault = False
    any_degraded = False

    if health is None:
        any_fault = True
        failures.append(("FAULT", "SYSTEM_UNHEALTHY"))
    else:
        if not health.map_loaded:
            any_fault = True
        health_fields = [
            health.edge_service, health.signal_input,
            health.localization_input, health.clock_status,
        ]
        for f in health_fields:
            if f == "FAULT":
                any_fault = True
            elif f == "DEGRADED":
                any_degraded = True

    if established_signal is not None and established_signal.source_health == "FAULT":
        any_fault = True
    elif established_signal is not None and established_signal.source_health == "DEGRADED":
        any_degraded = True

    if localization is not None and localization.health == "FAULT":
        any_fault = True
    elif localization is not None and localization.health == "DEGRADED":
        any_degraded = True

    if any_fault:
        Hv = False
        failures.append(("FAULT", "SYSTEM_UNHEALTHY"))
    elif any_degraded:
        Hv = False
        failures.append(("UNAVAILABLE", "SYSTEM_DEGRADED"))
    else:
        Hv = True

    # ----------------------------------------------------------------
    # 8. Timing constraints  (Tv)
    # ----------------------------------------------------------------
    remaining_time_ms: Optional[int] = None

    if established_signal is not None:
        remaining_time_ms = established_signal.remaining_time_ms

    if Sv and Cv:  # only meaningful when signal is WALK and crosswalk is established
        if remaining_time_ms is None:
            if cfg.get("require_remaining_time", True):
                failures.append(("WAIT", "INSUFFICIENT_REMAINING_TIME"))
            else:
                Tv = True
        elif remaining_time_ms < cfg["minimum_remaining_walk_time_ms"]:
            failures.append(("WAIT", "INSUFFICIENT_REMAINING_TIME"))
        else:
            Tv = True

    # ----------------------------------------------------------------
    # 9 & 10. Produce guidance state and reason codes
    # ----------------------------------------------------------------
    # Deduplicate reason codes while preserving order
    seen: set = set()
    unique_failures: List[tuple[str, str]] = []
    for item in failures:
        if item not in seen:
            seen.add(item)
            unique_failures.append(item)

    if unique_failures:
        # Pick most conservative decision
        final_decision = unique_failures[0][0]
        reason_codes = [rc for _, rc in unique_failures]
        for dec, _ in unique_failures[1:]:
            final_decision = _more_conservative(final_decision, dec)
    else:
        # All predicates passed
        Sv = Cv = Lv = Fv = Hv = Tv = True
        final_decision = "WALK"
        reason_codes = ["ALL_REQUIRED_CONDITIONS_VALID"]

    guidance = GuidanceDecision(
        decision=final_decision,
        reason_codes=reason_codes,
        intersection_id=map_id,
        crosswalk_id=established_cw_id,
        decision_timestamp_ms=now_ms,
    )

    evidence: Dict[str, Any] = {
        # Predicate results
        "Sv": Sv, "Cv": Cv, "Lv": Lv, "Fv": Fv, "Hv": Hv, "Tv": Tv,
        # Derived values
        "established_crosswalk_id": established_cw_id,
        "candidate_crosswalks": candidate_crosswalks,
        "signal_age_ms": signal_age_ms,
        "localization_age_ms": localization_age_ms,
        "remaining_time_ms": remaining_time_ms,
        "position_uncertainty_m": (
            localization.position_uncertainty_m if localization else None
        ),
        "signal_state": (
            established_signal.signal_state if established_signal else None
        ),
        "signal_source_health": (
            established_signal.source_health if established_signal else None
        ),
        "localization_health": (
            localization.health if localization else None
        ),
        "system_healthy": Hv,
        "signal_valid": Sv,
        "localization_valid": Lv,
        "crosswalk_match": Cv,
        # Thresholds used (for log reconstruction)
        "thresholds": {
            "signal_freshness_ms": cfg["signal_freshness_ms"],
            "localization_freshness_ms": cfg["localization_freshness_ms"],
            "max_position_uncertainty_m": cfg["max_position_uncertainty_m"],
            "minimum_remaining_walk_time_ms": cfg["minimum_remaining_walk_time_ms"],
            "require_remaining_time": cfg.get("require_remaining_time", True),
            "wrong_intersection_result": cfg.get("wrong_intersection_result", "UNAVAILABLE"),
        },
    }

    return EvaluationResult(decision=guidance, evidence=evidence)
