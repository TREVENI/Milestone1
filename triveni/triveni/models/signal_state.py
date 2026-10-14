"""signal_state.py – SignalState data model.

Represents the pedestrian signal reading for one crosswalk at one point in time.
Technology-independent: future adapters (NTCIP, V2X Hub, BLE, etc.) convert
real messages into this object.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# Accepted raw values for signal_state (including alias)
_VALID_SIGNAL_STATES = {"WALK", "DONT_WALK", "DON'T_WALK", "CLEARANCE"}
_VALID_SOURCE_HEALTH = {"OK", "DEGRADED", "FAULT"}


@dataclass
class SignalState:
    """Technology-independent representation of a pedestrian signal state.

    Fields
    ------
    intersection_id : str
        Must be non-empty; identifies the intersection this signal belongs to.
    crosswalk_id : str
        Must be non-empty; identifies which crosswalk this signal covers.
    signal_state : str
        Normalised to one of WALK | DONT_WALK | CLEARANCE.
        The raw alias "DON'T_WALK" is accepted and normalised to DONT_WALK.
    remaining_time_ms : int or None
        Milliseconds left in the current phase.  Optional.
    source_timestamp_ms : int
        When the traffic controller produced this data (epoch-ms).
    receive_timestamp_ms : int
        When TRIVENI received this data (epoch-ms).
    source_health : str
        Health of the signal source: OK | DEGRADED | FAULT.
    """

    intersection_id: str
    crosswalk_id: str
    signal_state: str
    source_timestamp_ms: int
    receive_timestamp_ms: int
    source_health: str
    remaining_time_ms: Optional[int] = None

    def __post_init__(self) -> None:
        # --- intersection / crosswalk identity ---
        if not self.intersection_id or not isinstance(self.intersection_id, str):
            raise ValueError("SignalState: intersection_id must be a non-empty string.")
        if not self.crosswalk_id or not isinstance(self.crosswalk_id, str):
            raise ValueError("SignalState: crosswalk_id must be a non-empty string.")

        # --- signal state (normalise alias) ---
        raw = self.signal_state
        if raw not in _VALID_SIGNAL_STATES:
            raise ValueError(
                f"SignalState: unsupported signal_state {raw!r}. "
                f"Must be one of {sorted(_VALID_SIGNAL_STATES)}."
            )
        # Normalise alias
        if raw == "DON'T_WALK":
            object.__setattr__(self, "signal_state", "DONT_WALK")

        # --- source health ---
        if self.source_health not in _VALID_SOURCE_HEALTH:
            raise ValueError(
                f"SignalState: invalid source_health {self.source_health!r}. "
                f"Must be one of {sorted(_VALID_SOURCE_HEALTH)}."
            )

        # --- timestamps ---
        if not isinstance(self.source_timestamp_ms, int) or not isinstance(
            self.receive_timestamp_ms, int
        ):
            raise TypeError("SignalState: timestamps must be integers (ms).")

        # --- optional remaining_time ---
        if self.remaining_time_ms is not None:
            if not isinstance(self.remaining_time_ms, int) or self.remaining_time_ms < 0:
                raise ValueError(
                    "SignalState: remaining_time_ms must be a non-negative integer or None."
                )
