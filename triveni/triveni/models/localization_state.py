"""localization_state.py – LocalizationState data model.

Represents the pedestrian's position/heading/confidence at one point in time.
Technology-independent: future adapters (UWB, BLE AoA, GNSS, vision fusion)
convert real measurements into this object.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


_VALID_HEALTH = {"OK", "DEGRADED", "FAULT"}
_VALID_SOURCE = {"SIMULATED"}  # Only SIMULATED is valid in Milestone 01


@dataclass
class LocalizationState:
    """Technology-independent pedestrian localization snapshot.

    Fields
    ------
    intersection_id : str
        Non-empty; identifies the intersection this position was reported for.
    x_m : float
        East position in meters from intersection center.
    y_m : float
        North position in meters from intersection center.
    heading_deg : float
        Heading in degrees (0 = East, 90 = North, counter-clockwise).
    position_uncertainty_m : float
        1-sigma radius of position uncertainty; must be >= 0.
    localization_source : str
        Must be "SIMULATED" in Milestone 01.
    timestamp_ms : int
        When this localization was produced (epoch-ms).
    health : str
        Health of the localization sub-system: OK | DEGRADED | FAULT.
    """

    intersection_id: str
    x_m: float
    y_m: float
    heading_deg: float
    position_uncertainty_m: float
    localization_source: str
    timestamp_ms: int
    health: str

    def __post_init__(self) -> None:
        # --- intersection identity ---
        if not self.intersection_id or not isinstance(self.intersection_id, str):
            raise ValueError(
                "LocalizationState: intersection_id must be a non-empty string."
            )

        # --- numeric fields ---
        for name, val in [
            ("x_m", self.x_m),
            ("y_m", self.y_m),
            ("heading_deg", self.heading_deg),
        ]:
            if not isinstance(val, (int, float)):
                raise TypeError(f"LocalizationState: {name} must be numeric.")

        # --- uncertainty: must be a non-negative number ---
        if not isinstance(self.position_uncertainty_m, (int, float)):
            raise TypeError("LocalizationState: position_uncertainty_m must be numeric.")
        if self.position_uncertainty_m < 0:
            raise ValueError(
                f"LocalizationState: position_uncertainty_m must be >= 0, "
                f"got {self.position_uncertainty_m}."
            )

        # --- localization source ---
        if self.localization_source not in _VALID_SOURCE:
            raise ValueError(
                f"LocalizationState: unsupported localization_source "
                f"{self.localization_source!r}. Must be one of {sorted(_VALID_SOURCE)}."
            )

        # --- timestamp ---
        if not isinstance(self.timestamp_ms, int):
            raise TypeError("LocalizationState: timestamp_ms must be an integer (ms).")

        # --- health ---
        if self.health not in _VALID_HEALTH:
            raise ValueError(
                f"LocalizationState: invalid health {self.health!r}. "
                f"Must be one of {sorted(_VALID_HEALTH)}."
            )
