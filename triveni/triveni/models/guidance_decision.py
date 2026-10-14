"""guidance_decision.py – GuidanceDecision data model.

Represents the single output of the safety engine for one evaluation tick.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


_VALID_DECISIONS = {"WALK", "WAIT", "UNAVAILABLE", "FAULT"}


@dataclass
class GuidanceDecision:
    """Immutable output of one safety-engine evaluation.

    Fields
    ------
    decision : str
        Exactly one of WALK | WAIT | UNAVAILABLE | FAULT.
    reason_codes : list[str]
        Non-empty list of reason codes explaining the decision.
    intersection_id : str
        Intersection this decision was made for.
    crosswalk_id : str or None
        Crosswalk this decision was made for (None if not established).
    decision_timestamp_ms : int
        When this decision was produced (epoch-ms).
    """

    decision: str
    reason_codes: List[str]
    intersection_id: str
    decision_timestamp_ms: int
    crosswalk_id: Optional[str] = None

    def __post_init__(self) -> None:
        # --- decision value ---
        if self.decision not in _VALID_DECISIONS:
            raise ValueError(
                f"GuidanceDecision: invalid decision {self.decision!r}. "
                f"Must be one of {sorted(_VALID_DECISIONS)}."
            )

        # --- reason codes ---
        if not isinstance(self.reason_codes, list) or len(self.reason_codes) == 0:
            raise ValueError(
                "GuidanceDecision: reason_codes must be a non-empty list."
            )

        # --- intersection identity ---
        if not self.intersection_id or not isinstance(self.intersection_id, str):
            raise ValueError(
                "GuidanceDecision: intersection_id must be a non-empty string."
            )

        # --- timestamp ---
        if not isinstance(self.decision_timestamp_ms, int):
            raise TypeError(
                "GuidanceDecision: decision_timestamp_ms must be an integer (ms)."
            )
