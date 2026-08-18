"""
Interactive Leaflet.js HTML Map Dossier Exporter for MCGM DP 2034.

Generates a clean, distraction-free, professional GIS dossier
with essential controls only: 2-way Base Switcher (Cadastral / Satellite),
high-contrast styling (Crimson Red Plot vs Electric Cyan Roads),
Net Developable buildable envelope, and measure tool.
"""
import json
from typing import List, Optional

from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union


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
    properties: dict,
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
        "geometry": {"type": "Polygon" if len(net_rings) == 1 else "MultiPolygon",
                     "coordinates": net_rings if len(net_rings) == 1 else [net_rings]},
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
                res_features.append({
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": [ring]},
                    "properties": {
                        "category": "RESERVATION",
                        "code": item.get("code", "RES"),
                        "type": item.get("type", "Reservation"),
                        "overlap_sqm": round(item.get("overlap_sqm", 0), 2),
                        "overlap_percent": round(item.get("overlap_percent", 0), 1),
                    },
                })

    des_features = []
    for item in all_des:
        for ring in item.get("wgs_rings", []):
            if len(ring) >= 3:
                des_features.append({
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": [ring]},
                    "properties": {
                        "category": "DESIGNATION",
                        "code": item.get("code", "DES"),
                        "description": item.get("description", "Designation"),
                        "overlap_sqm": round(item.get("overlap_sqm", 0), 2),
                        "overlap_percent": round(item.get("overlap_percent", 0), 1),
                    },
                })

    neighbor_features = []
    for n in (neighbors or []):
        for ring in n.get("rings", []):
            if len(ring) >= 3:
                neighbor_features.append({
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": [ring]},
                    "properties": {
                        "cts_no": n.get("cts_no", "N/A"),
                        "ward": n.get("ward", ""),
                    },
                })

    road_features = []
    for r_line in (roads or []):
        if len(r_line) >= 2:
            road_features.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": r_line},
                "properties": {
                    "road_name": properties.get("abutting_road") or "Abutting Road",
                    "road_width": properties.get("road_width") or "N/A",
                },
            })

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
    res_pill_html = f'<div class="layer-pill active" id="layerRes" onclick="toggleOverlay(\'res\')"><div class="pill-dot" style="background:var(--res-amber)"></div> 🟡 Reservations ({len(all_res)})</div>' if all_res else ""
    des_pill_html = f'<div class="layer-pill active" id="layerDes" onclick="toggleOverlay(\'des\')"><div class="pill-dot" style="background:#8b5cf6"></div> 🟣 Designations ({len(all_des)})</div>' if all_des else ""

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>DP Dossier Map — {properties.get('village', '')} CTS {properties.get('cts_no', '')}</title>
  
  <!-- Leaflet CSS & JS -->
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin=""/>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
  
  <!-- Google Fonts: Inter -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">

  <style>
    :root {{
      --bg-panel: rgba(255, 255, 255, 0.95);
      --border-panel: rgba(226, 232, 240, 0.95);
      --text-primary: #0f172a;
      --text-secondary: #475569;
      --text-muted: #94a3b8;
      --brand-primary: #2563eb;
      --plot-red: #e11d48;
      --road-cyan: #0284c7;
      --net-emerald: #10b981;
      --res-amber: #f59e0b;
      --font-sans: 'Inter', system-ui, -apple-system, sans-serif;
      --font-mono: 'JetBrains Mono', monospace;
    }}

    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body, html {{ height: 100%; width: 100%; font-family: var(--font-sans); color: var(--text-primary); overflow: hidden; background: #0f172a; }}

    #map {{ height: 100%; width: 100%; z-index: 1; }}

    /* Dossier HUD Sidebar */
    .dossier-hud {{
      position: absolute;
      top: 16px;
      left: 16px;
      width: 375px;
      max-height: calc(100vh - 32px);
      background: var(--bg-panel);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      border: 1px solid var(--border-panel);
      border-radius: 14px;
      box-shadow: 0 16px 40px -4px rgba(0, 0, 0, 0.22), 0 4px 12px -2px rgba(0, 0, 0, 0.08);
      z-index: 1000;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1);
    }}

    .dossier-hud.collapsed {{
      transform: translateX(-405px);
    }}

    .hud-toggle-btn {{
      position: absolute;
      top: 16px;
      left: 16px;
      z-index: 999;
      background: #ffffff;
      border: 1px solid var(--border-panel);
      border-radius: 10px;
      padding: 10px 16px;
      font-weight: 700;
      font-size: 13px;
      cursor: pointer;
      box-shadow: 0 4px 16px rgba(0,0,0,0.18);
      display: none;
    }}

    .hud-header {{
      padding: 16px 18px 12px;
      background: linear-gradient(180deg, #f8fafc 0%, #ffffff 100%);
      border-bottom: 1px solid var(--border-panel);
    }}

    .hud-header-top {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 4px;
    }}

    .hud-tag {{
      font-size: 10px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--brand-primary);
      background: #eff6ff;
      padding: 3px 8px;
      border-radius: 6px;
      border: 1px solid #bfdbfe;
    }}

    .hud-close-btn {{
      background: transparent;
      border: none;
      font-size: 18px;
      cursor: pointer;
      color: var(--text-muted);
    }}
    .hud-close-btn:hover {{ color: var(--text-primary); }}

    .hud-title {{
      font-size: 19px;
      font-weight: 800;
      letter-spacing: -0.02em;
      color: var(--text-primary);
    }}

    .hud-subtitle {{
      font-size: 12px;
      font-weight: 500;
      color: var(--text-secondary);
      margin-top: 1px;
    }}

    .status-badge {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 5px 11px;
      margin-top: 8px;
      border-radius: 8px;
      font-size: 11.5px;
      font-weight: 700;
      color: #ffffff;
      background: {badge_bg};
    }}

    .hud-body {{
      padding: 14px 18px;
      overflow-y: auto;
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 13px;
    }}

    /* 2-Way Base Map Toggle Switch */
    .basemap-switch {{
      background: #e2e8f0;
      border-radius: 9px;
      padding: 3px;
      display: flex;
      gap: 3px;
    }}

    .basemap-switch-btn {{
      flex: 1;
      background: transparent;
      border: none;
      padding: 7px 10px;
      border-radius: 7px;
      font-size: 11.5px;
      font-weight: 700;
      color: var(--text-secondary);
      cursor: pointer;
      text-align: center;
      transition: all 0.15s ease;
    }}

    .basemap-switch-btn.active {{
      background: #ffffff;
      color: var(--text-primary);
      box-shadow: 0 2px 5px rgba(0,0,0,0.12);
    }}

    /* Stat Card Grid */
    .stat-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }}

    .stat-card {{
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 10px;
      padding: 9px 11px;
    }}

    .stat-card-label {{
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--text-muted);
      margin-bottom: 2px;
    }}

    .stat-card-value {{
      font-size: 15px;
      font-weight: 800;
      font-family: var(--font-mono);
      color: var(--text-primary);
    }}

    .stat-card-sub {{
      font-size: 10px;
      color: var(--text-muted);
      margin-top: 1px;
    }}

    /* Encumbrance Progress Meter */
    .meter-section {{
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 10px;
      padding: 10px 12px;
    }}

    .meter-header {{
      display: flex;
      justify-content: space-between;
      font-size: 11px;
      font-weight: 700;
      margin-bottom: 5px;
    }}

    .meter-bar {{
      height: 9px;
      border-radius: 5px;
      background: #e2e8f0;
      display: flex;
      overflow: hidden;
      margin-bottom: 6px;
    }}

    .meter-fill-enc {{
      background: var(--plot-red);
      height: 100%;
    }}

    .meter-fill-net {{
      background: var(--net-emerald);
      height: 100%;
    }}

    .meter-legend {{
      display: flex;
      justify-content: space-between;
      font-size: 10px;
      font-weight: 600;
    }}

    /* Planning details list */
    .detail-list {{
      display: flex;
      flex-direction: column;
      gap: 6px;
      font-size: 11.5px;
    }}

    .detail-row {{
      display: flex;
      justify-content: space-between;
      padding-bottom: 4px;
      border-bottom: 1px dashed #e2e8f0;
    }}

    .detail-label {{
      color: var(--text-secondary);
      font-weight: 500;
    }}

    .detail-val {{
      font-weight: 700;
      color: var(--text-primary);
      text-align: right;
    }}

    /* Clean Essential Layer Toggles */
    .layer-controls {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }}

    .layer-pill {{
      display: flex;
      align-items: center;
      gap: 6px;
      background: #ffffff;
      border: 1px solid #cbd5e1;
      padding: 5px 10px;
      border-radius: 20px;
      font-size: 11px;
      font-weight: 700;
      cursor: pointer;
      user-select: none;
      transition: all 0.15s;
    }}

    .layer-pill.active {{
      background: #0f172a;
      color: #ffffff;
      border-color: #0f172a;
    }}

    .pill-dot {{
      width: 8px;
      height: 8px;
      border-radius: 50%;
    }}

    /* HUD Actions */
    .hud-actions {{
      padding: 12px 18px;
      background: #f8fafc;
      border-top: 1px solid var(--border-panel);
      display: flex;
      gap: 8px;
    }}

    .btn {{
      flex: 1;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      padding: 8px 12px;
      border-radius: 8px;
      font-size: 12px;
      font-weight: 700;
      cursor: pointer;
      text-decoration: none;
      border: 1px solid transparent;
      transition: all 0.15s ease;
    }}

    .btn-primary {{
      background: var(--brand-primary);
      color: #ffffff;
    }}
    .btn-primary:hover {{ background: #1d4ed8; }}

    .btn-outline {{
      background: #ffffff;
      color: var(--text-primary);
      border-color: #cbd5e1;
    }}
    .btn-outline:hover {{ background: #f1f5f9; }}

    /* Leaflet popup styling */
    .leaflet-popup-content-wrapper {{
      border-radius: 10px;
      box-shadow: 0 10px 25px rgba(0,0,0,0.2);
      font-family: var(--font-sans);
      padding: 4px;
    }}
    .custom-popup {{
      font-size: 12px;
      line-height: 1.5;
    }}
    .custom-popup h4 {{
      font-size: 13.5px;
      font-weight: 800;
      margin-bottom: 4px;
    }}

    /* Floating map tools (Top-Right) */
    .floating-tools {{
      position: absolute;
      top: 16px;
      right: 16px;
      z-index: 1000;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }}

    .tool-btn {{
      background: var(--bg-panel);
      backdrop-filter: blur(12px);
      border: 1px solid var(--border-panel);
      border-radius: 8px;
      width: 40px;
      height: 40px;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      box-shadow: 0 4px 12px rgba(0,0,0,0.15);
      font-size: 17px;
      color: var(--text-primary);
      transition: all 0.2s;
    }}
    .tool-btn:hover {{ background: #ffffff; transform: scale(1.05); }}
  </style>
</head>
<body>

  <button class="hud-toggle-btn" id="hudToggleBtn" onclick="toggleHud()">📋 Show Plot Dossier</button>

  <div id="map"></div>

  <!-- Essential Floating Tools on Right -->
  <div class="floating-tools">
    <button class="tool-btn" onclick="fitPlotBounds()" title="Center & Fit Plot">🎯</button>
    <button class="tool-btn" onclick="toggleMeasureMode()" id="measureBtn" title="Distance Measure Tool">📏</button>
    <button class="tool-btn" onclick="toggleBaseImagery()" id="floatingSatBtn" title="Toggle Satellite / Cadastral Map">🛰️</button>
  </div>

  <!-- Dossier HUD Panel -->
  <div class="dossier-hud" id="dossierHud">
    <div class="hud-header">
      <div class="hud-header-top">
        <span class="hud-tag">MCGM SDP 2034 DOSSIER</span>
        <button class="hud-close-btn" onclick="toggleHud()">✕</button>
      </div>
      <div class="hud-title">{properties.get('village', '').upper()} CTS {properties.get('cts_no', '')}</div>
      <div class="hud-subtitle">Ward {properties.get('ward', '')} · Zone {properties.get('zone', 'R')}</div>
      <div class="status-badge">{properties.get('status_badge', '🟢 CLEAR')}</div>
    </div>

    <div class="hud-body">
      <!-- 2-Way Base Map Toggle -->
      <div class="basemap-switch">
        <button class="basemap-switch-btn active" id="btn-sat" onclick="setBase('sat')">🛰️ Satellite View</button>
        <button class="basemap-switch-btn" id="btn-cad" onclick="setBase('cad')">🗺️ Cadastral Map</button>
      </div>

      <!-- Area Statistics -->
      <div class="stat-grid">
        <div class="stat-card">
          <div class="stat-card-label">Gross Plot Area</div>
          <div class="stat-card-value" style="color:var(--plot-red)">{area_sqm:,.1f} <span style="font-size:11px;font-weight:600">m²</span></div>
          <div class="stat-card-sub">{area_sqft:,.0f} sq.ft</div>
        </div>
        <div class="stat-card">
          <div class="stat-card-label">Net Developable</div>
          <div class="stat-card-value" style="color:var(--net-emerald)">{net_sqm:,.1f} <span style="font-size:11px;font-weight:600">m²</span></div>
          <div class="stat-card-sub">{net_pct:.1f}% usable</div>
        </div>
      </div>

      <!-- Encumbrance Bar Meter -->
      <div class="meter-section">
        <div class="meter-header">
          <span>Encumbrance Split</span>
          <span style="color:{'var(--plot-red)' if enc_sqm > 0 else 'var(--net-emerald)'}">{enc_pct:.1f}% Reserved</span>
        </div>
        <div class="meter-bar">
          <div class="meter-fill-enc" style="width:{enc_pct}%"></div>
          <div class="meter-fill-net" style="width:{net_pct}%"></div>
        </div>
        <div class="meter-legend">
          <span>🟢 Net: {net_sqm:,.0f} m²</span>
          <span>🔴 Encumbered: {enc_sqm:,.0f} m²</span>
        </div>
      </div>

      <!-- Planning Attributes -->
      <div class="detail-list">
        <div class="detail-row">
          <span class="detail-label">DP 2034 Zone</span>
          <span class="detail-val">Zone {properties.get('zone', 'R')}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">Abutting Road</span>
          <span class="detail-val" style="color:var(--road-cyan)">{properties.get('abutting_road') or 'N/A'} ({properties.get('road_width') or 'N/A'})</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">CRZ Restriction</span>
          <span class="detail-val">{properties.get('crz_buffer_flag') or 'NO'}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">Metro Rail Buffer</span>
          <span class="detail-val">{properties.get('metro_buffer_flag') or 'NO'}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">Adjoining Plots</span>
          <span class="detail-val">{len(neighbors or [])} CTS parcels</span>
        </div>
      </div>

      <!-- Useful Essential Overlays Only -->
      <div>
        <div style="font-size:10px;font-weight:700;text-transform:uppercase;color:var(--text-muted);margin-bottom:6px;">Visible Layers</div>
        <div class="layer-controls">
          <div class="layer-pill active" id="layerPlot" onclick="toggleOverlay('plot')">
            <div class="pill-dot" style="background:var(--plot-red)"></div> 🔴 Plot Boundary
          </div>
          <div class="layer-pill active" id="layerRoads" onclick="toggleOverlay('roads')">
            <div class="pill-dot" style="background:var(--road-cyan)"></div> 🛣️ Abutting Road
          </div>
          <div class="layer-pill active" id="layerNet" onclick="toggleOverlay('net')">
            <div class="pill-dot" style="background:var(--net-emerald)"></div> 🟢 Net Envelope
          </div>
          {res_pill_html}
          {des_pill_html}
          <div class="layer-pill active" id="layerNeigh" onclick="toggleOverlay('neigh')">
            <div class="pill-dot" style="background:#64748b"></div> 📍 Neighbours ({len(neighbors or [])})
          </div>
        </div>
      </div>
    </div>

    <!-- Quick Action Footer -->
    <div class="hud-actions">
      <button class="btn btn-outline" onclick="window.print()">🖨️ Print Map</button>
      <button class="btn btn-primary" onclick="fitPlotBounds()">🎯 Center Plot</button>
    </div>
  </div>

  <script>
    const DATA = {json.dumps(dossier_data)};

    // Initialize Leaflet Map
    const center = DATA.plot_identity.center;
    const map = L.map('map', {{
      center: center,
      zoom: 18,
      zoomControl: false,
    }});

    L.control.zoom({{ position: 'bottomright' }}).addTo(map);

    // High-Resolution Base Tile Layers
    const baseLayers = {{
      sat: L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}', {{
        attribution: 'Esri World Imagery',
        maxZoom: 19
      }}),
      cad: L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
        attribution: '&copy; CartoDB &copy; OpenStreetMap',
        maxZoom: 19
      }})
    }};

    let currentBase = 'sat';
    baseLayers.sat.addTo(map);

    function setBase(key) {{
      if (key === currentBase) return;
      map.removeLayer(baseLayers[currentBase]);
      baseLayers[key].addTo(map);
      currentBase = key;

      // Bring vector overlays to front
      Object.values(overlayLayers).forEach(layer => {{
        if (map.hasLayer(layer) && layer.bringToFront) layer.bringToFront();
      }});

      document.getElementById('btn-sat').classList.toggle('active', key === 'sat');
      document.getElementById('btn-cad').classList.toggle('active', key === 'cad');
      const floatBtn = document.getElementById('floatingSatBtn');
      if (floatBtn) floatBtn.textContent = key === 'sat' ? '🗺️' : '🛰️';
    }}

    function toggleBaseImagery() {{
      setBase(currentBase === 'sat' ? 'cad' : 'sat');
    }}

    // Layer Storage
    const overlayLayers = {{}};

    // 1. Abutting Roads Layer (HIGH-CONTRAST ELECTRIC CYAN)
    overlayLayers.roads = L.geoJSON(DATA.roads, {{
      style: {{
        color: '#0284c7',
        weight: 6,
        opacity: 0.95,
        dashArray: '8, 6',
      }},
      onEachFeature: (feature, layer) => {{
        layer.bindPopup(`
          <div class="custom-popup">
            <h4 style="color:#0284c7">🛣️ Abutting Road Alignment</h4>
            <div><b>Road:</b> ${{feature.properties.road_name}}</div>
            <div><b>Width:</b> ${{feature.properties.road_width}}</div>
          </div>
        `);
      }}
    }}).addTo(map);

    // 2. Base Plot Boundary (VIVID CRIMSON RED with Corner Vertex Markers)
    overlayLayers.plot = L.geoJSON(DATA.base_plot, {{
      style: {{
        color: '#e11d48',
        weight: 3.5,
        opacity: 1.0,
        fillColor: '#e11d48',
        fillOpacity: 0.12,
      }},
      onEachFeature: (feature, layer) => {{
        layer.bindPopup(`
          <div class="custom-popup">
            <h4 style="color:#e11d48">🔴 Plot Boundary (Cadastral)</h4>
            <div><b>CTS / CS No:</b> ${{DATA.plot_identity.cts_no}}</div>
            <div><b>Village:</b> ${{DATA.plot_identity.village}}</div>
            <div><b>Ward:</b> ${{DATA.plot_identity.ward}}</div>
            <div><b>Gross Area:</b> ${{DATA.plot_identity.area_sqm.toLocaleString()}} m² (${{DATA.plot_identity.area_sqft.toLocaleString()}} sq.ft)</div>
            <div><b>Zone:</b> Zone ${{DATA.plot_identity.zone}}</div>
          </div>
        `);
      }}
    }}).addTo(map);

    // Corner Vertex Markers
    if (DATA.base_plot.geometry && DATA.base_plot.geometry.coordinates[0]) {{
      DATA.base_plot.geometry.coordinates[0].forEach((pt, i) => {{
        L.circleMarker([pt[1], pt[0]], {{
          radius: 4,
          color: '#e11d48',
          fillColor: '#ffffff',
          fillOpacity: 1.0,
          weight: 2
        }}).bindTooltip(`Corner ${{i + 1}}: [${{pt[1].toFixed(5)}}, ${{pt[0].toFixed(5)}}]`).addTo(map);
      }});
    }}

    // 3. Net Developable Layer (EMERALD GREEN)
    overlayLayers.net = L.geoJSON(DATA.net_plot, {{
      style: {{
        color: '#059669',
        weight: 2.5,
        opacity: 0.9,
        fillColor: '#10b981',
        fillOpacity: 0.28,
      }},
      onEachFeature: (feature, layer) => {{
        layer.bindPopup(`
          <div class="custom-popup">
            <h4 style="color:#059669">🟢 Net Developable Envelope</h4>
            <div><b>Net Usable Area:</b> ${{DATA.plot_identity.net_sqm.toLocaleString()}} m²</div>
            <div><b>Percentage:</b> ${{DATA.plot_identity.net_percent}}% of gross parcel</div>
            <div><b>Status:</b> Unencumbered Zone ${{DATA.plot_identity.zone}} land</div>
          </div>
        `);
      }}
    }}).addTo(map);

    // 4. Reservations Layer (VIVID AMBER)
    if (DATA.reservations.features.length > 0) {{
      overlayLayers.res = L.geoJSON(DATA.reservations, {{
        style: {{
          color: '#d97706',
          weight: 2.5,
          fillColor: '#f59e0b',
          fillOpacity: 0.5,
          dashArray: '4, 4'
        }},
        onEachFeature: (feature, layer) => {{
          const p = feature.properties;
          layer.bindPopup(`
            <div class="custom-popup">
              <h4 style="color:#d97706">🟡 Statutory Reservation</h4>
              <div><b>Code:</b> ${{p.code}}</div>
              <div><b>Type:</b> ${{p.type}}</div>
              <div><b>Overlap:</b> ${{p.overlap_sqm.toLocaleString()}} m² (${{p.overlap_percent}}%)</div>
            </div>
          `);
        }}
      }}).addTo(map);
    }}

    // 5. Designations Layer (DEEP PURPLE)
    if (DATA.designations.features.length > 0) {{
      overlayLayers.des = L.geoJSON(DATA.designations, {{
        style: {{
          color: '#7c3aed',
          weight: 2.5,
          fillColor: '#8b5cf6',
          fillOpacity: 0.45,
          dashArray: '3, 3'
        }},
        onEachFeature: (feature, layer) => {{
          const p = feature.properties;
          layer.bindPopup(`
            <div class="custom-popup">
              <h4 style="color:#7c3aed">🟣 Existing Designation</h4>
              <div><b>Code:</b> ${{p.code}}</div>
              <div><b>Description:</b> ${{p.description}}</div>
              <div><b>Overlap:</b> ${{p.overlap_sqm.toLocaleString()}} m² (${{p.overlap_percent}}%)</div>
            </div>
          `);
        }}
      }}).addTo(map);
    }}

    // 6. Neighbours Layer (SLATE GREY)
    overlayLayers.neigh = L.geoJSON(DATA.neighbors, {{
      style: {{
        color: '#64748b',
        weight: 1.5,
        fillColor: '#94a3b8',
        fillOpacity: 0.12,
        dashArray: '2, 4'
      }},
      onEachFeature: (feature, layer) => {{
        layer.bindPopup(`
          <div class="custom-popup">
            <h4>📍 Adjoining Parcel</h4>
            <div><b>CTS Number:</b> ${{feature.properties.cts_no}}</div>
          </div>
        `);
      }}
    }}).addTo(map);

    // Initial Zoom Fit
    function fitPlotBounds() {{
      if (overlayLayers.plot && overlayLayers.plot.getBounds().isValid()) {{
        map.fitBounds(overlayLayers.plot.getBounds(), {{
          paddingTopLeft: [390, 30],
          paddingBottomRight: [30, 30],
          maxZoom: 19
        }});
      }}
    }}

    fitPlotBounds();

    // Toggle Overlay Layers
    function toggleOverlay(layerKey) {{
      const layer = overlayLayers[layerKey];
      const pill = document.getElementById('layer' + layerKey.charAt(0).toUpperCase() + layerKey.slice(1));
      if (!layer) return;
      if (map.hasLayer(layer)) {{
        map.removeLayer(layer);
        if (pill) pill.classList.remove('active');
      }} else {{
        map.addLayer(layer);
        if (pill) pill.classList.add('active');
      }}
    }}

    // Toggle HUD
    function toggleHud() {{
      const hud = document.getElementById('dossierHud');
      const toggleBtn = document.getElementById('hudToggleBtn');
      hud.classList.toggle('collapsed');
      toggleBtn.style.display = hud.classList.contains('collapsed') ? 'block' : 'none';
    }}

    // Measure Tool Mode
    let measureMode = false;
    let measurePoints = [];
    let measureLine = null;

    function toggleMeasureMode() {{
      measureMode = !measureMode;
      const btn = document.getElementById('measureBtn');
      if (measureMode) {{
        btn.style.background = '#2563eb';
        btn.style.color = '#ffffff';
        map.getContainer().style.cursor = 'crosshair';
      }} else {{
        btn.style.background = '';
        btn.style.color = '';
        map.getContainer().style.cursor = '';
        if (measureLine) map.removeLayer(measureLine);
        measurePoints = [];
      }}
    }}

    map.on('click', (e) => {{
      if (!measureMode) return;
      measurePoints.push(e.latlng);
      if (measureLine) map.removeLayer(measureLine);
      measureLine = L.polyline(measurePoints, {{ color: '#2563eb', weight: 3, dashArray: '5, 5' }}).addTo(map);
      if (measurePoints.length > 1) {{
        let totalDist = 0;
        for (let i = 0; i < measurePoints.length - 1; i++) {{
          totalDist += measurePoints[i].distanceTo(measurePoints[i + 1]);
        }}
        L.popup()
          .setLatLng(e.latlng)
          .setContent(`<b>Measured Distance:</b> ${{totalDist.toFixed(2)}} meters (${{(totalDist * 3.28084).toFixed(1)}} ft)`)
          .openOn(map);
      }}
    }});
  </script>
</body>
</html>
"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
