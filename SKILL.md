---
name: dp-lookup-pro
description: >-
  Enterprise Pro Level 3 DP Plot Lookup & GIS Exporter for Mumbai (MCGM SDP 2014-34).
  Queries Zoning, Land Reservations, DP Modification Orders, CRZ Coastal Restrictions, Metro Rail Buffers, Road Widths, and Adjoining Plot Clusters.
  Generates 2-Page PDF Remark Dockets, Retina HD DP Maps, Esri Satellite Views, AutoCAD DXF Drawing Files, GeoJSON, and Google Earth 3D KML exports.
version: 3.10.0
command: /dp-lookup-pro
parameters:
  type: object
  properties:
    village:
      type: string
      description: "Exact MCGM revenue village name, one of 128 valid values (e.g., 'BANDRA-A', 'WORLI', 'MALABAR HILL'). Note: 'BANDRA' alone is NOT valid — use BANDRA-A..BANDRA-I or BANDRA-EAST."
    cts_number:
      type: string
      description: "CTS or CS plot number (e.g., '100', '748A', '16/738')"
    output_dir:
      type: string
      description: "Optional destination directory for export bundle subfolders and Excel logs (default: './output')"
    use_cache:
      type: boolean
      description: "Set false (or pass --no-cache) to force a fresh network lookup. Cached reports expire after 30 days and report their age."
  required: ["village", "cts_number"]
---

# `dp-lookup-pro` Skill & Command (Enterprise Level)

## Pro Capabilities

1. **🏷️ Planning Status Badges**: Classifies land parcels (`🟢 CLEAR`, `🟡 MODIFIED`, `🔴 RESERVED`).
2. **🌊 Precise CRZ & Infrastructure Detection**: Queries plot-specific Coastal Regulation Zone (CRZ-I/II/III/IV) restriction boundaries & Layer 1550 Metro Rail Influence buffers.
3. **📸 Dual High-Definition Visuals**: Generates Retina HD DP 2034 Map Overlay with North Arrow ($N \uparrow$) and scale legend, alongside Tile-Stitched Esri World Imagery Satellite Aerial Views.
4. **📐 Direct AutoCAD DXF & GeoJSON Exports**: Generates native AutoCAD `.dxf` drawing files (compatible with AutoCAD LT, Civil 3D, and standard CAD) and scale-accurate `.geojson` (QGIS/ArcGIS).
5. **🌍 Google Earth 3D Exports**: Generates interactive 3D `.kml` files with metadata popups for Google Earth.
6. **📄 Auto-Generated 2-Page PDF Docket**: Generates a 2-page downloadable **DP Remark PDF Report** complete with formatted data tables, status banners, maps, adjoining parcel cluster tables, and a scannable interactive map **QR Code**.
7. **📁 Dedicated Query Export Subfolders**: Isolates all query assets inside clean bundle subfolders (`output/<village_name>_cts_<cts_no>/`).
8. **⚡ Concurrency & Persistent Disk Cache**: Single-batch HTTP/2 pipelining (~5-13 s cold, 25 requests) with a 30-day disk cache for instant repeat lookups. Cache hits report their age, self-invalidate if the files are gone, and incomplete results are never cached.

## Tooling Standards

* **Python Runtime & Package Management**: Use **`uv`** (`uv run`). Standard `pip` or system `python` calls can be used as fallback.
* **JavaScript Runtime**: Use **`bun`** (`bun run`, `bun add`).

## Usage

### 1. Slash Command (Agent Chat)
```text
/dp-lookup-pro <VILLAGE_NAME> <CTS_NUMBER>
```

### 2. Terminal CLI Command
```bash
uv run python dp-lookup-pro "<VILLAGE_NAME>" "<CTS_NUMBER>" [OUTPUT_DIR] [--no-cache]
```

Use the `uv run python` form — it works on macOS, Linux and Windows alike.
After `uv pip install -e .` the command `dp-lookup-pro` also works from any folder.

## Result reliability

Check `metadata.complete` before trusting a result. `false` means one or more
lookups failed and `metadata.warnings` explains which; such runs are never cached.
`plot_identity.area_source` says whether the area is MCGM-approved or derived
from the plot boundary.
