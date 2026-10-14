"""event_logger.py – Structured decision logger.

Writes exactly ONE JSON record per decision (one line) to a JSON Lines (.jsonl)
file.  Every field needed to reconstruct a decision is included.

Use triveni.logging.event_logger (not stdlib logging) to avoid shadowing the
standard library's `logging` module.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from triveni.models.guidance_decision import GuidanceDecision


# Required top-level fields (spec §9)
_REQUIRED_FIELDS = (
    "decision_timestamp_ms",
    "intersection_id",
    "crosswalk_id",
    "signal",
    "signal_age_ms",
    "position_uncertainty_m",
    "crosswalk_match",
    "signal_valid",
    "localization_valid",
    "system_healthy",
    "decision",
    "reason_codes",
)


class EventLogger:
    """Writes one JSON Line per decision to a .jsonl log file.

    Parameters
    ----------
    log_path : str or Path
        Path to the JSON Lines log file.  Parent directories are created
        automatically.
    mode : str, default "w"
        File mode at initialization. "w" clears old results so each run starts
        fresh. "a" preserves existing content.
    """

    def __init__(self, log_path: str | Path, mode: str = "w") -> None:
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.mode = mode
        if mode == "w":
            with open(self.log_path, "w", encoding="utf-8") as fh:
                pass

    def log(
        self,
        decision: GuidanceDecision,
        evidence: Dict[str, Any],
    ) -> None:
        """Write one log record to the .jsonl file.

        Parameters
        ----------
        decision : GuidanceDecision
            The engine output for this tick.
        evidence : dict
            The evidence dict returned by the safety engine (contains
            per-predicate results, ages, thresholds, etc.).
        """
        record = _build_record(decision, evidence)
        with open(self.log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")


def _build_record(
    decision: GuidanceDecision,
    evidence: Dict[str, Any],
) -> Dict[str, Any]:
    """Build the log record containing exactly the 12 required fields (spec §9)."""
    return {
        "decision_timestamp_ms": decision.decision_timestamp_ms,
        "intersection_id": decision.intersection_id,
        "crosswalk_id": decision.crosswalk_id,
        "signal": evidence.get("signal_state"),
        "signal_age_ms": evidence.get("signal_age_ms"),
        "position_uncertainty_m": evidence.get("position_uncertainty_m"),
        "crosswalk_match": evidence.get("crosswalk_match"),
        "signal_valid": evidence.get("signal_valid"),
        "localization_valid": evidence.get("localization_valid"),
        "system_healthy": evidence.get("system_healthy"),
        "decision": decision.decision,
        "reason_codes": decision.reason_codes,
    }
