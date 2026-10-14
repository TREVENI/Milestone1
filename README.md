# TRIVENI milestone 1

---

## Setup

```bash
python -m venv .venv

# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

---

## Run

```bash
# All demos in sequence
python run_demo.py

# With pauses for live demo / screen recording
python run_demo.py --pause

# Run all tests
pytest -v
```



## How it works

TRIVENI answers one question per tick:

> *Given signal state, crosswalk information, pedestrian position/confidence, timing, and system health — what guidance should TRIVENI produce?*

Output is exactly **one** of `WALK | WAIT | UNAVAILABLE | FAULT` plus one or more reason codes.

### SPaT mapping (Signal Phase and Timing)

| Physical display | `signal_state` field |
|---|---|
| Pedestrian green man (WALK) | `WALK` |
| Flashing hand (clearance) | `CLEARANCE` |
| Red man (DON'T WALK) | `DONT_WALK` |
| Time left in current phase | `remaining_time_ms` |
| Time controller produced data | `source_timestamp_ms` |
| Time TRIVENI received it | `receive_timestamp_ms` |

**Signal age** = `now_ms - source_timestamp_ms`.  Stale if age > `signal_freshness_ms`.  
Only the **pedestrian signal** of each crosswalk is used. Nothing connects to a real signal in this milestone.  
**WALK alone does NOT mean "cross"** — all six safety predicates must hold.

### Pedestrian zones

Each crosswalk has two zones (polygons in meters from intersection centre):  
- **Entry zone** — where the pedestrian *waits* to cross (curb side).  
- **Exit zone** — the far side (destination side).  

The pedestrian's position is a circle: centre = `(x_m, y_m)`, radius = `position_uncertainty_m`.  
The engine tests whether this circle overlaps a zone.

### Per-tick decision loop

```
for every tick:
    1. Check intersection identity
    2. Check crosswalk identity (find entry-zone overlaps)
    3. Check signal state (WALK / DONT_WALK / CLEARANCE)
    4. Check signal freshness & timestamp validity
    5. Check localization freshness & timestamp validity
    6. Check localization uncertainty
    7. Check system health
    8. Check timing (remaining walk time)
    9. Produce exactly ONE guidance state
   10. Produce >= 1 reason codes
```

### Six safety predicates (all must hold for WALK)

| Predicate | Meaning |
|---|---|
| **Sv** | Signal state is valid and is WALK |
| **Cv** | Intended crosswalk is established (exactly one entry zone overlap) |
| **Lv** | Localization is present, same intersection, uncertainty <= max |
| **Fv** | Required information is fresh |
| **Hv** | Required system components are healthy |
| **Tv** | Enough remaining walk time |

**Priority (most conservative wins):** `FAULT > UNAVAILABLE > WAIT > WALK`

Any uncaught exception -> `FAULT / UNKNOWN_ERROR` (never WALK).

---

## Demos A-E

### Demo A — Valid crossing
CW_NORTH = WALK, pedestrian at (5.5, 9.5) in CW_NORTH entry, fresh data, system healthy.  
**Expected: WALK / ALL_REQUIRED_CONDITIONS_VALID**

### Demo B — Ambiguous crosswalk
CW_NORTH = WALK, pedestrian at (8.0, 8.0) — shared NE corner of CW_NORTH entry and CW_EAST exit.  
**Expected: UNAVAILABLE / CROSSWALK_AMBIGUOUS**

### Demo C — Stale signal
CW_NORTH = WALK, signal age 900 ms (above 500 ms threshold).  
**Expected: UNAVAILABLE / SIGNAL_STALE**

### Demo D — DON'T WALK signal
CW_NORTH = DONT_WALK.  
**Expected: WAIT / SIGNAL_NOT_WALK**

### Demo E — Journey replay (100 000 ms to 120 000 ms, 1 tick/s)

| Stage | Time (ms) | Signal | Pedestrian |
|---|---|---|---|
| 1 | 100 000 - 104 999 | DONT_WALK | Waiting at (5.5, 9.5) CW_NORTH entry |
| 2 | 105 000 - 105 999 | WALK (18 s) | Still at curb |
| 3 | 106 000 - 112 499 | WALK | Walking west at 0.8 m/s |
| 4 | 112 500 - 120 000 | WALK | Past entry zone, far side |

> **Note:** Once the pedestrian leaves the CW_NORTH entry zone in Stage 3 the engine outputs  
> `UNAVAILABLE / CROSSWALK_NOT_ESTABLISHED` — mid-crossing guidance is not defined in Milestone 01.  
> See *Known limitations* below.

---

## Reason code table

| Code | Meaning |
|---|---|
| `ALL_REQUIRED_CONDITIONS_VALID` | All predicates Sv-Tv passed -> WALK |
| `SIGNAL_NOT_WALK` | Signal is DONT_WALK or CLEARANCE |
| `SIGNAL_MISSING` | No SignalState for established crosswalk |
| `SIGNAL_STALE` | Signal age > `signal_freshness_ms` |
| `SIGNAL_TIMESTAMP_INVALID` | Contradictory or future source timestamp |
| `LOCALIZATION_MISSING` | No localization data |
| `LOCALIZATION_STALE` | Localization age > `localization_freshness_ms` |
| `LOCALIZATION_TIMESTAMP_INVALID` | Negative or future localization timestamp |
| `LOCALIZATION_UNCERTAINTY_TOO_HIGH` | uncertainty_m > `max_position_uncertainty_m` |
| `WRONG_INTERSECTION` | Data belongs to a different intersection |
| `CROSSWALK_AMBIGUOUS` | Position circle overlaps zones of >1 crosswalk |
| `CROSSWALK_NOT_ESTABLISHED` | Position not in any entry zone |
| `CROSSWALK_MISMATCH` | Established crosswalk != intended crosswalk |
| `SYSTEM_UNHEALTHY` | A critical component has FAULT status |
| `SYSTEM_DEGRADED` | A component is DEGRADED (no FAULT present) |
| `INSUFFICIENT_REMAINING_TIME` | Remaining walk time < minimum threshold |
| `UNKNOWN_ERROR` | Unexpected exception -> always FAULT, never WALK |

---

## Technology adapter table

| Future technology | Internal TRIVENI object |
|---|---|
| Traffic controller / simulator | `SignalState` |
| UWB / BLE / GNSS / vision / fusion | `LocalizationState` |
| J2735 MAP / GeoJSON / manual map | `CrosswalkMap` |
| Edge hardware monitoring | `SystemHealth` |
| Android / wearable | `GuidanceDecision` |

*Future adapters convert real technologies into these objects, so feasibility can be tested without redesigning the architecture.*

---

## Known limitations / next milestone

- **Mid-crossing guidance not defined.** Once a pedestrian leaves the entry zone, the engine outputs `UNAVAILABLE / CROSSWALK_NOT_ESTABLISHED`.  This is intentional; Milestone 02 will define mid-crossing and exit-zone semantics.
- **`localization_source` must be `"SIMULATED"`** in this milestone.  Real adapters will add other allowed values.
- No real-time hardware integration of any kind.

---

## Assumptions

Where the specification was ambiguous the most conservative (non-WALK) interpretation was applied:

1. **Ambiguity rule:** A position that overlaps *any* zone (entry or exit) of more than one crosswalk is treated as CROSSWALK_AMBIGUOUS, not just entry-entry overlaps.  This is the safest interpretation and matches the spec statement "find every crosswalk whose ENTRY or EXIT zone overlaps the circle… more than one crosswalk -> CROSSWALK_AMBIGUOUS".
2. **Missing `require_remaining_time`:** Defaults to `true` if absent from config.
3. **`wrong_intersection_result`:** Defaults to `UNAVAILABLE` if absent from config.
