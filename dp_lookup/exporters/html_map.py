"""
Interactive Leaflet.js HTML Map Dossier Exporter for MCGM DP 2034.

Generates a clean, distraction-free, professional GIS dossier
with essential controls only: 2-way Base Switcher (Cadastral / Satellite),
high-contrast styling (Crimson Red Plot vs Electric Cyan Roads),
Net Developable buildable envelope, and measure tool.
"""

import json
import math
import re
from html import escape as _escape_html
from importlib import resources
from typing import Any, Dict, List, Mapping, Optional, Sequence

from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

from dp_lookup.exporters.contracts import ExportPayload, legacy_export_properties

_TEMPLATE_NAME = "html_map.html"
_TEMPLATE_TOKEN_RE = re.compile(r"@@D(?P<index>[0-9]+)@@")
_ASSET_TOKEN_RE = re.compile(r"@@A(?P<index>[0-9]+)@@")


def _json_for_html(value: object) -> str:
    """Serialize data for a script block without permitting HTML breakout."""
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _render_resource_template(name: str, token_re: re.Pattern[str], values: Sequence[str]) -> str:
    template = resources.files("dp_lookup.exporters.templates").joinpath(name).read_text(encoding="utf-8")
    matches = list(token_re.finditer(template))
    indexes = {int(match.group("index")) for match in matches}
    expected = set(range(len(values)))
    if indexes != expected:
        raise ValueError(f"{name} tokens {sorted(indexes)} do not match {sorted(expected)}")
    return token_re.sub(lambda match: values[int(match.group("index"))], template)


def _render_html_template(values: Sequence[str]) -> str:
    """Render the packaged HTML shell and reject token contract drift."""
    return _render_resource_template(_TEMPLATE_NAME, _TEMPLATE_TOKEN_RE, values)


def _render_asset_template(name: str, values: Sequence[str]) -> str:
    """Render a packaged first-party CSS or JavaScript asset strictly."""
    return _render_resource_template(name, _ASSET_TOKEN_RE, values)


def _finite_number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _area_presentation(properties: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize the typed area assessment and retain legacy direct-call support."""
    legacy_area = _finite_number(properties.get("area_sqm"))
    raw_assessment = properties.get("area_assessment")
    if not isinstance(raw_assessment, Mapping):
        legacy_source = str(properties.get("area_source") or "").casefold()
        boundary_only = any(token in legacy_source for token in ("boundary", "derived", "shape.area"))
        recorded = None if boundary_only else legacy_area
        calculated = legacy_area if boundary_only else None
        return {
            "recorded": recorded,
            "calculated": calculated,
            "selected": legacy_area,
            "difference_sqm": None,
            "difference_percent": None,
            "reliability_status": "screening",
            "reliability_label": "Screening",
            "recorded_source": "MCGM cadastral parcel record",
            "geometry_source": "MCGM cadastral parcel boundary",
        }

    recorded = _finite_number(raw_assessment.get("recorded_plot_area_sqm"))
    calculated = _finite_number(raw_assessment.get("calculated_boundary_area_sqm"))
    selected = _finite_number(raw_assessment.get("selected_area_sqm"))
    if selected is None:
        selected = legacy_area if legacy_area is not None else (recorded if recorded is not None else calculated)
    difference_sqm = _finite_number(raw_assessment.get("difference_sqm"))
    difference_percent = _finite_number(raw_assessment.get("difference_percent"))
    if difference_sqm is None and recorded is not None and calculated is not None:
        difference_sqm = calculated - recorded
    if difference_percent is None and recorded is not None and recorded != 0.0 and difference_sqm is not None:
        difference_percent = abs(difference_sqm) / recorded * 100.0
    raw_reliability_status = str(raw_assessment.get("reliability_status") or "screening")
    reliability_status = (
        raw_reliability_status
        if raw_reliability_status in {"screening", "verified_source", "qualified_with_warnings", "certified"}
        else "screening"
    )
    reliability_label = {
        "screening": "Screening",
        "verified_source": "Verified source",
        "qualified_with_warnings": "Qualified with warnings",
        "certified": "Certified",
    }[reliability_status]
    return {
        "recorded": recorded,
        "calculated": calculated,
        "selected": selected,
        "difference_sqm": difference_sqm,
        "difference_percent": difference_percent,
        "reliability_status": reliability_status,
        "reliability_label": reliability_label,
        "recorded_source": str(raw_assessment.get("recorded_area_source") or "MCGM cadastral parcel record"),
        "geometry_source": str(raw_assessment.get("geometry_source") or "MCGM cadastral parcel boundary"),
    }


def _area_value_text(value: Optional[float]) -> str:
    return f"{value:,.2f} m²" if value is not None else "Not available"


def _area_difference_text(area: Mapping[str, Any]) -> str:
    difference_sqm = _finite_number(area.get("difference_sqm"))
    difference_percent = _finite_number(area.get("difference_percent"))
    if difference_sqm is None or difference_percent is None:
        return "Not comparable"
    return f"{difference_percent:.2f}% ({difference_sqm:+,.2f} m²)"


def _area_sources_text(area: Mapping[str, Any]) -> str:
    sources = []
    if _finite_number(area.get("recorded")) is not None:
        sources.append(f"Recorded: {area['recorded_source']}")
    if _finite_number(area.get("calculated")) is not None:
        sources.append(f"Boundary: {area['geometry_source']}")
    return " · ".join(sources) if sources else "Area source unavailable"


def _authority_text(properties: Mapping[str, Any]) -> tuple[str, str]:
    raw = properties.get("authority_resolution")
    if not isinstance(raw, Mapping):
        return "", "is-hidden"
    active_ids = raw.get("active_record_ids")
    if not isinstance(active_ids, (list, tuple)) or not active_ids:
        return "", "is-hidden"
    selected = []
    for purpose in ("area", "geometry"):
        item = raw.get(purpose)
        if isinstance(item, Mapping) and item.get("source_label"):
            selected.append(f"{purpose}: {item['source_label']}")
    planning = raw.get("planning")
    if isinstance(planning, list):
        selected.extend(
            f"planning: {item['source_label']}"
            for item in planning
            if isinstance(item, Mapping) and item.get("source_label")
        )
    detail = "; ".join(selected) if selected else "explicitly activated source evidence"
    ids = ", ".join(str(value) for value in active_ids)
    return f"Authority selection - {detail} (record IDs: {ids}). MCGM baseline retained.", ""


def _reliability_css_class(status: str) -> str:
    return {
        "verified_source": "reliability-verified",
        "qualified_with_warnings": "reliability-qualified",
        "certified": "reliability-certified",
    }.get(status, "reliability-screening")


def _compute_net_developable_wgs(
    wgs_rings: List[List[List[float]]],
    encumbered_items: Sequence[Mapping[str, Any]],
) -> List[List[List[float]]]:
    """Compute the unencumbered polygon in WGS84 coordinates using Shapely."""
    try:
        plot_poly = Polygon(wgs_rings[0])
        if not plot_poly.is_valid:
            plot_poly = plot_poly.buffer(0)

        enc_polys: List[Any] = []
        for item in encumbered_items:
            for ring in item.get("wgs_rings", []):
                if len(ring) >= 3:
                    p = Polygon(ring)
                    if not p.is_valid:
                        p = p.buffer(0)
                    enc_polys.append(p)

        if not enc_polys:
            return wgs_rings

        union_enc = unary_union(enc_polys)
        net_poly = plot_poly.difference(union_enc)
        if net_poly.is_empty:
            return []

        out_rings: List[List[List[float]]] = []
        parts = list(net_poly.geoms) if isinstance(net_poly, MultiPolygon) else [net_poly]
        for part in parts:
            if getattr(part, "exterior", None) is not None:
                coords = [[round(x, 7), round(y, 7)] for x, y in part.exterior.coords]
                if len(coords) >= 4:
                    out_rings.append(coords)
        return out_rings or wgs_rings
    except Exception:
        return wgs_rings


def export_html_map(
    wgs_rings: List[List[List[float]]],
    properties: ExportPayload,
    output_path: str,
    neighbors: Optional[List[Dict[str, Any]]] = None,
    roads: Optional[Sequence[Sequence[Sequence[float]]]] = None,
    reservations: Optional[List[Dict[str, Any]]] = None,
    designations: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """
    Generates a streamlined, clean HTML Map Dossier (.html)
    with Leaflet.js, fast Cadastral/Satellite toggle, and clear dossier metrics.
    """
    properties = legacy_export_properties(properties)
    all_res = reservations or []
    all_des = designations or []
    all_encumbered = all_res + all_des
    has_encumbrance = bool(all_encumbered)
    net_rings = _compute_net_developable_wgs(wgs_rings, all_encumbered)

    # Compute plot centroid for initial map view
    all_lons = [pt[0] for pt in wgs_rings[0]]
    all_lats = [pt[1] for pt in wgs_rings[0]]
    center_lat = sum(all_lats) / len(all_lats)
    center_lon = sum(all_lons) / len(all_lons)

    area_presentation = _area_presentation(properties)
    authority_text, authority_css_class = _authority_text(properties)
    area_sqm = float(area_presentation["selected"] or 0.0)
    area_sqft = area_sqm * 10.7639
    enc_pct = float(properties.get("encumbered_percent") or 0.0)
    if enc_pct <= 0.0:
        enc_sqm = 0.0
        net_sqm = area_sqm
        net_pct = 100.0
    else:
        enc_sqm = float(properties.get("encumbered_area_sqm") or round(area_sqm * (enc_pct / 100.0), 2))
        net_sqm = float(properties.get("net_unencumbered_sqm") or max(0.0, round(area_sqm - enc_sqm, 2)))
        net_pct = float(properties.get("net_unencumbered_percent") or max(0.0, round(100.0 - enc_pct, 2)))

    # Convert GeoJSON objects for client embedding
    base_plot_geojson = {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": wgs_rings},
        "properties": {
            "title": f"CTS {properties.get('cts_no')} ({properties.get('village')})",
            "area_sqm": area_sqm,
            "area_sqft": round(area_sqft, 2),
            "zone": properties.get("zone", "R"),
            "ward": properties.get("ward", "N/A"),
        },
    }

    net_coordinates: Any
    if len(net_rings) == 1:
        net_coordinates = net_rings
    else:
        net_coordinates = [net_rings]
    net_plot_geojson: Dict[str, Any] = {
        "type": "Feature",
        "geometry": {
            "type": "Polygon" if len(net_rings) == 1 else "MultiPolygon",
            "coordinates": net_coordinates,
        },
        "properties": {
            "title": "Net Developable Envelope",
            "net_sqm": round(net_sqm, 2),
            "net_percent": round(net_pct, 1),
        },
    }

    res_features = []
    for item in all_res:
        for ring in item.get("wgs_rings", []):
            if len(ring) >= 3:
                res_features.append(
                    {
                        "type": "Feature",
                        "geometry": {"type": "Polygon", "coordinates": [ring]},
                        "properties": {
                            "category": "RESERVATION",
                            "code": item.get("code", "RES"),
                            "type": item.get("type", "Reservation"),
                            "overlap_sqm": round(item.get("overlap_sqm", 0), 2),
                            "overlap_percent": round(item.get("overlap_percent", 0), 1),
                        },
                    }
                )

    des_features = []
    for item in all_des:
        for ring in item.get("wgs_rings", []):
            if len(ring) >= 3:
                des_features.append(
                    {
                        "type": "Feature",
                        "geometry": {"type": "Polygon", "coordinates": [ring]},
                        "properties": {
                            "category": "DESIGNATION",
                            "code": item.get("code", "DES"),
                            "description": item.get("description", "Designation"),
                            "overlap_sqm": round(item.get("overlap_sqm", 0), 2),
                            "overlap_percent": round(item.get("overlap_percent", 0), 1),
                        },
                    }
                )

    neighbor_features = []
    for n in neighbors or []:
        for ring in n.get("rings", []):
            if len(ring) >= 3:
                neighbor_features.append(
                    {
                        "type": "Feature",
                        "geometry": {"type": "Polygon", "coordinates": [ring]},
                        "properties": {
                            "cts_no": n.get("cts_no", "N/A"),
                            "ward": n.get("ward", ""),
                        },
                    }
                )

    road_features = []
    for r_line in roads or []:
        if len(r_line) >= 2:
            road_features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": r_line},
                    "properties": {
                        "road_name": properties.get("abutting_road") or "Abutting Road",
                        "road_width": properties.get("road_width") or "N/A",
                    },
                }
            )

    dossier_data = {
        "plot_identity": {
            "village": properties.get("village", "").upper(),
            "cts_no": properties.get("cts_no", ""),
            "ward": properties.get("ward", ""),
            "zone": properties.get("zone", "R"),
            "status_badge": properties.get("status_badge", "🟢 CLEAR"),
            "area_sqm": round(area_sqm, 2),
            "area_sqft": round(area_sqft, 2),
            "area_assessment": {
                "recorded_plot_area_sqm": area_presentation["recorded"],
                "calculated_boundary_area_sqm": area_presentation["calculated"],
                "difference_sqm": area_presentation["difference_sqm"],
                "difference_percent": area_presentation["difference_percent"],
                "reliability_status": area_presentation["reliability_status"],
                "reliability_label": area_presentation["reliability_label"],
                "recorded_area_source": area_presentation["recorded_source"],
                "geometry_source": area_presentation["geometry_source"],
            },
            "authority_resolution": properties.get("authority_resolution"),
            "geometry_source": area_presentation["geometry_source"],
            "encumbered_sqm": round(enc_sqm, 2),
            "encumbered_percent": round(enc_pct, 1),
            "net_sqm": round(net_sqm, 2),
            "net_percent": round(net_pct, 1),
            "crz_status": properties.get("crz_buffer_flag", "NO"),
            "metro_buffer": properties.get("metro_buffer_flag", "NO"),
            "road_name": properties.get("abutting_road") or "N/A",
            "road_width": properties.get("road_width") or "N/A",
            "modifications": properties.get("modification_approval") or "None",
            "has_encumbrance": has_encumbrance,
            "center": [center_lat, center_lon],
        },
        "base_plot": base_plot_geojson,
        "net_plot": net_plot_geojson,
        "reservations": {"type": "FeatureCollection", "features": res_features},
        "designations": {"type": "FeatureCollection", "features": des_features},
        "neighbors": {"type": "FeatureCollection", "features": neighbor_features},
        "roads": {"type": "FeatureCollection", "features": road_features},
    }

    badge_str = properties.get("status_badge", "")
    badge_bg = "#10b981" if badge_str.startswith("🟢") else ("#f59e0b" if badge_str.startswith("🟡") else "#ef4444")
    res_pill_html = (
        f'<div class="layer-pill active" id="layerRes" onclick="toggleOverlay(\'res\')"><div class="pill-dot" style="background:var(--res-amber)"></div> 🟡 Reservations ({len(all_res)})</div>'
        if all_res
        else ""
    )
    des_pill_html = (
        f'<div class="layer-pill active" id="layerDes" onclick="toggleOverlay(\'des\')"><div class="pill-dot" style="background:#8b5cf6"></div> 🟣 Designations ({len(all_des)})</div>'
        if all_des
        else ""
    )
    dossier_css = _render_asset_template("dossier.css", [badge_bg])
    dossier_js = _render_asset_template("dossier.js", [_json_for_html(dossier_data)])

    html_values = [
        _escape_html(properties.get("village", "")),
        _escape_html(properties.get("cts_no", "")),
        _escape_html(properties.get("village", "").upper()),
        _escape_html(properties.get("cts_no", "")),
        _escape_html(properties.get("ward", "")),
        _escape_html(properties.get("zone", "R")),
        _escape_html(properties.get("status_badge", "🟢 CLEAR")),
        f"{area_sqm:,.1f}",
        f"{area_sqft:,.0f}",
        f"{net_sqm:,.1f}",
        f"{net_pct:.1f}",
        "var(--plot-red)" if enc_sqm > 0 else "var(--net-emerald)",
        f"{enc_pct:.1f}",
        str(enc_pct),
        str(net_pct),
        f"{net_sqm:,.0f}",
        f"{enc_sqm:,.0f}",
        _escape_html(properties.get("zone", "R")),
        _escape_html(properties.get("abutting_road") or "N/A"),
        _escape_html(properties.get("road_width") or "N/A"),
        _escape_html(properties.get("crz_buffer_flag") or "NO"),
        _escape_html(properties.get("metro_buffer_flag") or "NO"),
        str(len(neighbors or [])),
        res_pill_html,
        des_pill_html,
        str(len(neighbors or [])),
        dossier_css,
        dossier_js,
        _escape_html(_area_value_text(area_presentation["recorded"])),
        _escape_html(_area_value_text(area_presentation["calculated"])),
        _escape_html(_area_difference_text(area_presentation)),
        _reliability_css_class(str(area_presentation["reliability_status"])),
        _escape_html(str(area_presentation["reliability_label"])),
        _escape_html(_area_sources_text(area_presentation)),
        _escape_html(authority_text),
        authority_css_class,
    ]
    html_content = _render_html_template(html_values)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
