"""crosswalk_map.py – CrosswalkMap data model and geometry helpers.

Loads the intersection map from data/intersection_demo.json and provides:
  - point_in_polygon(point, polygon) -> bool
  - circle_overlaps_polygon(cx, cy, r, polygon) -> bool
  - which_crosswalk_zones_overlap(x_m, y_m, uncertainty_m) ->
        list of (crosswalk_id, zone_type) tuples  (zone_type: "entry" | "exit")

Technology-independent: uses only the internal data objects.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _point_in_polygon(px: float, py: float, polygon: List[List[float]]) -> bool:
    """Ray-casting point-in-polygon test (Jordan curve theorem).

    Parameters
    ----------
    px, py   : point coordinates
    polygon  : list of [x, y] vertices (closed automatically)

    Returns True if (px, py) is inside or on the boundary of the polygon.
    """
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        # Check exact boundary membership on horizontal edge
        if (yi == py == yj) and (min(xi, xj) <= px <= max(xi, xj)):
            return True
        if ((yi > py) != (yj > py)) and (
            px < (xj - xi) * (py - yi) / (yj - yi) + xi
        ):
            inside = not inside
        j = i
    return inside


def _closest_point_on_segment(
    px: float, py: float, ax: float, ay: float, bx: float, by: float
) -> Tuple[float, float]:
    """Return the point on segment AB closest to P."""
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return ax, ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return ax + t * dx, ay + t * dy


def _circle_overlaps_polygon(
    cx: float, cy: float, radius: float, polygon: List[List[float]]
) -> bool:
    """Return True if the circle (cx, cy, radius) overlaps the polygon.

    Overlap means: the circle center is inside the polygon, OR the circle
    intersects any edge of the polygon.  A zero-radius circle degenerates
    to a point-in-polygon test.
    """
    # 1. Center inside polygon
    if _point_in_polygon(cx, cy, polygon):
        return True

    # 2. Circle intersects any edge
    n = len(polygon)
    for i in range(n):
        ax, ay = polygon[i]
        bx, by = polygon[(i + 1) % n]
        cpx, cpy = _closest_point_on_segment(cx, cy, ax, ay, bx, by)
        dist = math.hypot(cpx - cx, cpy - cy)
        if dist <= radius:
            return True

    return False


# ---------------------------------------------------------------------------
# CrosswalkMap
# ---------------------------------------------------------------------------

@dataclass
class _CrosswalkEntry:
    """Internal: one crosswalk's geometry data."""
    crosswalk_id: str
    entry_zone: List[List[float]]
    exit_zone: List[List[float]]
    heading_deg: float


@dataclass
class CrosswalkMap:
    """Loaded intersection map with geometry query helpers.

    Attributes
    ----------
    intersection_id : str
        Must match the intersection_id used in SignalState / LocalizationState.
    crosswalks : dict
        Mapping crosswalk_id -> _CrosswalkEntry.

    Construction
    ------------
    Use ``CrosswalkMap.from_json(path)`` to load from the JSON file, or
    ``CrosswalkMap.from_dict(data)`` to construct from a parsed dict.
    """

    intersection_id: str
    crosswalks: Dict[str, _CrosswalkEntry] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_json(cls, path: str | Path) -> "CrosswalkMap":
        """Load from data/intersection_demo.json (or any compatible JSON file)."""
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> "CrosswalkMap":
        """Construct from a parsed dict (same schema as intersection_demo.json)."""
        intersection_id = data.get("intersection_id", "")
        if not intersection_id:
            raise ValueError("CrosswalkMap: intersection_id is missing or empty.")

        obj = cls(intersection_id=intersection_id)
        for cw in data.get("crosswalks", []):
            cw_id = cw.get("crosswalk_id", "")
            if not cw_id:
                raise ValueError("CrosswalkMap: a crosswalk entry has no crosswalk_id.")
            obj.crosswalks[cw_id] = _CrosswalkEntry(
                crosswalk_id=cw_id,
                entry_zone=cw["entry_zone"],
                exit_zone=cw["exit_zone"],
                heading_deg=float(cw["heading_deg"]),
            )
        return obj

    # ------------------------------------------------------------------
    # Public geometry helpers
    # ------------------------------------------------------------------

    def point_in_polygon(self, point: Tuple[float, float], polygon: List[List[float]]) -> bool:
        """Public wrapper – True if point (x, y) is inside the polygon."""
        return _point_in_polygon(point[0], point[1], polygon)

    def circle_overlaps_polygon(
        self,
        cx: float,
        cy: float,
        radius: float,
        polygon: List[List[float]],
    ) -> bool:
        """Public wrapper – True if circle overlaps polygon."""
        return _circle_overlaps_polygon(cx, cy, radius, polygon)

    def which_crosswalk_zones_overlap(
        self,
        x_m: float,
        y_m: float,
        uncertainty_m: float,
    ) -> List[Tuple[str, str]]:
        """Return all (crosswalk_id, zone_type) pairs whose zone overlaps the circle.

        zone_type is either "entry" or "exit".
        The circle has center (x_m, y_m) and radius = uncertainty_m.
        A zero-radius (zero uncertainty) circle is treated as a point test.
        """
        results: List[Tuple[str, str]] = []
        for cw_id, cw in self.crosswalks.items():
            if _circle_overlaps_polygon(x_m, y_m, uncertainty_m, cw.entry_zone):
                results.append((cw_id, "entry"))
            if _circle_overlaps_polygon(x_m, y_m, uncertainty_m, cw.exit_zone):
                results.append((cw_id, "exit"))
        return results
