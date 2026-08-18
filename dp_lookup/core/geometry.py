"""
Core Coordinate, Projection, and Spatial Geometry Mathematics.
"""
import math
from typing import Any, Dict, List, Tuple

from dp_lookup.core.constants import (
    ROAD_EDGE_NUDGES,
    ROAD_EDGE_PROBE_LIMIT,
    WEB_MERCATOR_R,
)
from dp_lookup.core.topology import arcgis_rings_to_geometry


def wgs84_to_utm43n(lon: float, lat: float) -> Tuple[float, float]:
    """
    Direct ellipsoidal projection from WGS84 (degrees) to UTM Zone 43N (metres),
    EPSG:32643, using standard Karney/Krüger transverse-Mercator formulas on the
    WGS84 ellipsoid.
    """
    a = 6378137.0
    f = 1.0 / 298.257223563
    k0 = 0.9996
    lon0 = 75.0 * math.pi / 180.0  # Zone 43 central meridian

    phi = lat * math.pi / 180.0
    lam = lon * math.pi / 180.0 - lon0

    n = f / (2.0 - f)
    n2, n3, n4 = n * n, n * n * n, n * n * n * n

    A = a / (1.0 + n) * (1.0 + n2 / 4.0 + n4 / 64.0)

    alpha = (
        1.0 / 2.0 * n - 2.0 / 3.0 * n2 + 5.0 / 16.0 * n3,
        13.0 / 48.0 * n2 - 3.0 / 5.0 * n3,
        61.0 / 240.0 * n3,
    )

    t = math.sinh(math.atanh(math.sin(phi)) - 2.0 * math.sqrt(n) / (1.0 + n) * math.atanh(2.0 * math.sqrt(n) / (1.0 + n) * math.sin(phi)))
    xi_prime = math.atan2(t, math.cos(lam))
    eta_prime = math.atanh(math.sin(lam) / math.sqrt(1.0 + t * t))

    xi = xi_prime + sum(alpha[j - 1] * math.sin(2 * j * xi_prime) * math.cosh(2 * j * eta_prime) for j in (1, 2, 3))
    eta = eta_prime + sum(alpha[j - 1] * math.cos(2 * j * xi_prime) * math.sinh(2 * j * eta_prime) for j in (1, 2, 3))

    easting = 500000.0 + k0 * A * eta
    northing = k0 * A * xi
    return round(easting, 2), round(northing, 2)


def mercator_to_wgs84(x: float, y: float, precision: int = 7) -> List[float]:
    """Web Mercator (EPSG:102100/3857) metres to WGS84 degrees."""
    lon = round((x / WEB_MERCATOR_R) * 180, precision)
    lat = round(
        (math.atan(math.exp(y / WEB_MERCATOR_R * math.pi)) * 2 - math.pi / 2) * 180 / math.pi,
        precision,
    )
    return [lon, lat]


def latlon_to_tile(lat: float, lon: float, zoom: int) -> Tuple[int, int]:
    """Standard Slippy Map tile numbering for Web Mercator XYZ tiles."""
    lat_rad = math.radians(lat)
    n = 2.0 ** zoom
    xtile = int((lon + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return xtile, ytile


def tile_to_latlon(xtile: int, ytile: int, zoom: int) -> Tuple[float, float]:
    """Top-left corner coordinates of a Slippy Map tile."""
    n = 2.0 ** zoom
    lon_deg = xtile / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * ytile / n)))
    lat_deg = math.degrees(lat_rad)
    return lat_deg, lon_deg


def polygon_area(pts: List[List[float]]) -> float:
    """Shoelace formula for simple planar polygon area."""
    n = len(pts)
    s = 0.0
    for i in range(n):
        x1, y1 = pts[i][0], pts[i][1]
        x2, y2 = pts[(i + 1) % n][0], pts[(i + 1) % n][1]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def polygon_centroid(pts: List[List[float]]) -> Tuple[float, float]:
    """Polygon centroid via standard Shoelace-weighted moments."""
    n = len(pts)
    if n < 3:
        return (sum(p[0] for p in pts) / max(1, n), sum(p[1] for p in pts) / max(1, n))
    signed_area = 0.0
    cx = 0.0
    cy = 0.0
    for i in range(n):
        x0, y0 = pts[i][0], pts[i][1]
        x1, y1 = pts[(i + 1) % n][0], pts[(i + 1) % n][1]
        a = x0 * y1 - x1 * y0
        signed_area += a
        cx += (x0 + x1) * a
        cy += (y0 + y1) * a
    signed_area *= 0.5
    if abs(signed_area) < 1e-9:
        return (sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n)
    return (cx / (6.0 * signed_area), cy / (6.0 * signed_area))


def prepare_geometry(rings: list) -> Dict[str, Any]:
    """
    Everything derived from the parcel rings: centroid, bounding box, the
    half-extent used for map windows, and the WGS84 reprojection.
    """
    ring = rings[0]
    parcel_geometry = arcgis_rings_to_geometry(rings)
    if parcel_geometry.is_empty:
        cx = sum(p[0] for p in ring) / len(ring)
        cy = sum(p[1] for p in ring) / len(ring)
    else:
        representative = parcel_geometry.representative_point()
        cx, cy = representative.x, representative.y

    pts = [p for r in rings for p in r]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    mcx, mcy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    span = max(max(xs) - min(xs), max(ys) - min(ys))

    lon, lat = mercator_to_wgs84(cx, cy, precision=6)
    return {
        "cx": cx, "cy": cy, "mcx": mcx, "mcy": mcy,
        "xs": xs, "ys": ys,
        "d": max(50, span / 2),
        "lat": lat, "lon": lon,
        "wgs_rings": [[mercator_to_wgs84(p[0], p[1]) for p in r] for r in rings],
    }


def road_probe_points(
    outer_ring: list,
    mcx: float,
    mcy: float,
    xs: list,
    ys: list,
) -> List[Tuple[float, float]]:
    """
    Where to look for the abutting road.
    Centroid and both corners, plus the midpoints of the longest edges pushed outward at three distances.
    """
    edge_probes = []
    for i in range(len(outer_ring)):
        p1 = outer_ring[i]
        p2 = outer_ring[(i + 1) % len(outer_ring)]
        ex, ey = p2[0] - p1[0], p2[1] - p1[1]
        seg_len = math.hypot(ex, ey)
        if seg_len <= 0.01:
            continue
        emx, emy = (p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0
        enx, eny = -ey / seg_len, ex / seg_len
        # flip normal so it points away from parcel centre
        if (emx + enx - mcx) ** 2 + (emy + eny - mcy) ** 2 < (emx - mcx) ** 2 + (emy - mcy) ** 2:
            enx, eny = -enx, -eny
        for nudge in ROAD_EDGE_NUDGES:
            edge_probes.append((seg_len, (emx + enx * nudge, emy + eny * nudge)))

    edge_probes.sort(key=lambda e: e[0], reverse=True)
    return [
        (mcx, mcy),
        (min(xs), min(ys)),
        (max(xs), max(ys)),
    ] + [pt for _, pt in edge_probes[:ROAD_EDGE_PROBE_LIMIT]]


def neighbour_probe_points(mcx: float, mcy: float, d: float) -> List[Tuple[float, float]]:
    """Four cardinal offsets around the parcel."""
    off = max(15.0, d * 0.7)
    return [(mcx + off, mcy), (mcx - off, mcy), (mcx, mcy + off), (mcx, mcy - off)]


def nearest_road_geoms(
    road_geoms: list,
    wgs_rings: list,
    limit: int = 8,
) -> list:
    """The limit road paths closest to the plot."""
    if not road_geoms or not wgs_rings or not wgs_rings[0]:
        return road_geoms[:limit]
    ring = wgs_rings[0]
    lon0 = sum(p[0] for p in ring) / len(ring)
    lat0 = sum(p[1] for p in ring) / len(ring)
    lon_scale = math.cos(math.radians(lat0))

    def nearest_sq(path):
        best = float("inf")
        for pt in path:
            dx = (pt[0] - lon0) * lon_scale
            dy = pt[1] - lat0
            best = min(best, dx * dx + dy * dy)
        return best

    return sorted(road_geoms, key=nearest_sq)[:limit]


def resolve_plot_area(attrs: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve approved vs derived area from attributes."""
    for key in ("AREA_APP_SQ_MTRS", "Area_App_Sq_Mtrs", "area_app_sq_mtrs"):
        val = attrs.get(key)
        if val is not None and str(val).strip() not in ("", "0", "0.0", "null", "None"):
            try:
                area_num = float(val)
                if area_num > 0:
                    return {"area_sqm": area_num,
                            "area_source": "approved record (AREA_APP_SQ_MTRS)",
                            "note": None}
            except (TypeError, ValueError):
                pass

    for key in ("AREA_CAL_SQ_MTRS", "Area_Cal_Sq_Mtrs", "SHAPE.AREA", "Shape.STArea()", "st_area(shape)"):
        val = attrs.get(key)
        if val is not None and str(val).strip() not in ("", "0", "0.0", "null", "None"):
            try:
                area_num = float(val)
                if area_num > 0:
                    return {"area_sqm": round(area_num, 2),
                            "area_source": "derived from boundary (AREA_CAL_SQ_MTRS)",
                            "note": ("Area was not on record; derived from "
                                     "digitised boundary and is indicative only")}
            except (TypeError, ValueError):
                pass

    return {"area_sqm": None, "area_source": "unavailable", "note": None}
