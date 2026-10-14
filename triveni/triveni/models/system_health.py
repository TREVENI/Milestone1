"""system_health.py – SystemHealth data model.

Captures the health of each required system component at one point in time.
"""
from __future__ import annotations

from dataclasses import dataclass


_VALID_HEALTH = {"OK", "DEGRADED", "FAULT"}


@dataclass
class SystemHealth:
    """Snapshot of critical system component health.

    Fields
    ------
    edge_service : str
        Health of the edge processing service: OK | DEGRADED | FAULT.
    signal_input : str
        Health of the signal data pipeline: OK | DEGRADED | FAULT.
    localization_input : str
        Health of the localization data pipeline: OK | DEGRADED | FAULT.
    map_loaded : bool
        True if the crosswalk map has been successfully loaded.
    clock_status : str
        Health of the system clock / time-sync: OK | DEGRADED | FAULT.
    """

    edge_service: str
    signal_input: str
    localization_input: str
    map_loaded: bool
    clock_status: str

    def __post_init__(self) -> None:
        for field_name in ("edge_service", "signal_input", "localization_input", "clock_status"):
            val = getattr(self, field_name)
            if val not in _VALID_HEALTH:
                raise ValueError(
                    f"SystemHealth: invalid {field_name} value {val!r}. "
                    f"Must be one of {sorted(_VALID_HEALTH)}."
                )
        if not isinstance(self.map_loaded, bool):
            raise TypeError("SystemHealth: map_loaded must be a bool.")
