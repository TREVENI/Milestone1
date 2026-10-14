"""conftest.py – makes the triveni package importable when pytest is run from
the project root (triveni/) without needing an editable install.
Also writes:
  - logs/pytest_run.log          : PASS/FAIL per test with timestamps (fresh per run)
  - logs/test_decision_log.jsonl : exactly 1 line per test case (48 lines for 48 tests, fresh per run)
"""
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Add the project root to sys.path so absolute imports like
# `from triveni.models.signal_state import SignalState` work.
_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT))

# ---------------------------------------------------------------------------
# Log file paths
# ---------------------------------------------------------------------------
_LOG_FILE = _ROOT / "logs" / "pytest_run.log"
_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

_DECISION_LOG = _ROOT / "logs" / "test_decision_log.jsonl"
_DECISION_LOG.parent.mkdir(parents=True, exist_ok=True)

# State tracking per running test
_current_test_name = ["<unknown>"]
_current_evaluations: List[Tuple[Any, Dict[str, Any]]] = []


def pytest_sessionstart(session):
    """Clear logs at session start so new run overwrites old results (no append across runs)."""
    with open(_LOG_FILE, "w", encoding="utf-8") as f:
        f.write(f"{'='*68}\n")
        f.write(f"TEST RUN STARTED  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"{'='*68}\n")

    # Clear test decision log (start completely fresh)
    with open(_DECISION_LOG, "w", encoding="utf-8") as fh:
        pass

    # Monkey-patch evaluate() to collect decisions evaluated inside tests
    import triveni.safety.safety_engine as _se
    _orig_evaluate = _se.evaluate

    def _patched_evaluate(*args, **kwargs):
        result = _orig_evaluate(*args, **kwargs)
        _current_evaluations.append((result.decision, result.evidence))
        return result

    _se.evaluate = _patched_evaluate


def pytest_runtest_protocol(item, nextitem):
    """Track which test is running and reset per-test evaluation collector."""
    _current_test_name[0] = item.nodeid
    _current_evaluations.clear()


def pytest_runtest_logreport(report):
    """Called after each test phase.

    Writes exactly ONE line to test_decision_log.jsonl per test case (48 tests -> 48 lines).
    """
    if report.when != "call" and not (report.when == "setup" and report.failed):
        return

    status = "PASSED" if report.passed else ("FAILED" if report.failed else "ERROR")

    # 1. Update logs/pytest_run.log
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {status:<8}  {report.nodeid}"
    if report.failed and report.longreprtext:
        detail = report.longreprtext.strip().splitlines()
        line += "\n" + "\n".join(f"           {l}" for l in detail[-6:])
    with open(_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

    # 2. Write exactly ONE JSON line to logs/test_decision_log.jsonl
    from triveni.logging.event_logger import _build_record
    if _current_evaluations:
        last_decision, last_evidence = _current_evaluations[-1]
        record = _build_record(last_decision, last_evidence)
        record["test_name"] = report.nodeid
        record["test_status"] = status
        record["call_count"] = len(_current_evaluations)
        if len(_current_evaluations) > 1:
            record["all_decisions"] = [d.decision for d, _ in _current_evaluations]
    else:
        # Unit / validation test that tested models/helpers without calling evaluate()
        record = {
            "decision_timestamp_ms": None,
            "intersection_id": "INT_KEMPS_CORNER",
            "crosswalk_id": None,
            "signal": None,
            "signal_age_ms": None,
            "position_uncertainty_m": None,
            "crosswalk_match": None,
            "signal_valid": None,
            "localization_valid": None,
            "system_healthy": None,
            "decision": "N/A",
            "reason_codes": ["UNIT_TEST_PASS" if report.passed else "UNIT_TEST_FAIL"],
            "test_name": report.nodeid,
            "test_status": status,
            "call_count": 0,
        }

    with open(_DECISION_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")


def pytest_sessionfinish(session, exitstatus):
    """Write summary to pytest_run.log only (no marker in test_decision_log so line count = test count)."""
    passed = session.testscollected - session.testsfailed
    failed = session.testsfailed
    summary = (
        f"\nSUMMARY  passed={passed}  failed={failed}  "
        f"exit={exitstatus}  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"{'='*68}\n"
    )
    with open(_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(summary)
