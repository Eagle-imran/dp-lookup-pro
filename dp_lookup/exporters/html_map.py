"""
Interactive Leaflet.js HTML Map Dossier Exporter for MCGM DP 2034.

Generates a clean, distraction-free, professional GIS dossier
with essential controls only: 2-way Base Switcher (Cadastral / Satellite),
high-contrast styling (Crimson Red Plot vs Electric Cyan Roads),
Net Developable buildable envelope, and measure tool.
"""

import json
import re
from html import escape as _escape_html
from importlib import resources
from typing import List, Optional, Sequence

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


def _compute_net_developable_wgs(wgs_rings: list, encumbered_items: list) -> List[List[List[float]]]:
    """Compute the unencumbered polygon in WGS84 coordinates using Shapely."""
    try:
        plot_poly = Polygon(wgs_rings[0])
        if not plot_poly.is_valid:
            plot_poly = plot_poly.buffer(0)

        enc_polys = []
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

        out_rings = []
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
    wgs_rings: list,
    properties: ExportPayload,
    output_path: str,
    neighbors: Optional[list] = None,
    roads: Optional[list] = None,
    reservations: Optional[list] = None,
    designations: Optional[list] = None,
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

    area_sqm = float(properties.get("area_sqm") or 0.0)
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

    net_plot_geojson = {
        "type": "Feature",
        "geometry": {
            "type": "Polygon" if len(net_rings) == 1 else "MultiPolygon",
            "coordinates": net_rings if len(net_rings) == 1 else [net_rings],
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
    ]
    html_content = _render_html_template(html_values)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
