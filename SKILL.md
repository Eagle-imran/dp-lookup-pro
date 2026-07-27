---
name: cts-dplookup-pro
description: >-
  Enterprise Pro Level 3 DP Plot Lookup & GIS Exporter for Mumbai (MCGM SDP 2014-34).
  Queries Zoning, Land Reservations, DP Modification Orders, CRZ Coastal Restrictions, Metro Rail Buffers, Road Widths, and Adjoining Plot Clusters.
  Generates 2-Page PDF Remark Dockets, Retina HD DP Maps, Esri Satellite Views, AutoCAD GeoJSON, and Google Earth 3D KML exports.
version: 3.5.0
command: /cts-dplookup-pro
parameters:
  type: object
  properties:
    village:
      type: string
      description: "Name of the Mumbai village (e.g., 'BANDRA', 'WORLI', 'MALABAR HILL')"
    cts_number:
      type: string
      description: "CTS or CS plot number (e.g., '100', '748A', '16/738')"
    output_dir:
      type: string
      description: "Optional destination directory for export bundle subfolders and Excel logs (default: './output')"
  required: ["village", "cts_number"]
---

# `cts-dplookup-pro` Skill & Command (Enterprise Level)

## Pro Capabilities

1. **🏷️ Planning Status Badges**: Classifies land parcels (`🟢 CLEAR`, `🟡 MODIFIED`, `🔴 RESERVED`).
2. **🌊 Precise CRZ & Infrastructure Detection**: Queries plot-specific Coastal Regulation Zone (CRZ-I/II/III/IV) restriction boundaries & Layer 1550 Metro Rail Influence buffers.
3. **📸 Dual High-Definition Visuals**: Generates Retina HD DP 2034 Map Overlay with North Arrow ($N \uparrow$) and scale legend, alongside Tile-Stitched Esri World Imagery Satellite Aerial Views.
4. **🌍 GIS CAD & Google Earth Exports**: Generates scale-accurate `.geojson` (AutoCAD/QGIS) and `.kml` (Google Earth 3D) files in WGS84 (`EPSG:4326`).
5. **📄 Auto-Generated 2-Page PDF Docket**: Generates a 2-page downloadable **DP Remark PDF Report** complete with formatted data tables, status banners, maps, adjoining parcel cluster tables, and a scannable interactive map **QR Code**.
6. **📁 Dedicated Query Export Subfolders**: Isolates all query assets inside clean bundle subfolders (`output/<village_name>_cts_<cts_no>/`).
7. **⚡ High-Speed Concurrency & Persistent Disk Cache**: Sub-second HTTP/2 async pipelining with persistent disk caching (~12 ms for repeat lookups).

## Tooling Standards

* **Python Runtime & Package Management**: Use **`uv`** (`uv run`). Standard `pip` or system `python` calls can be used as fallback.
* **JavaScript Runtime**: Use **`bun`** (`bun run`, `bun add`).

## Usage

### 1. Slash Command (Agent Chat)
```text
/cts-dplookup-pro <VILLAGE_NAME> <CTS_NUMBER>
```

### 2. Terminal CLI Command
```bash
./cts-dplookup-pro "<VILLAGE_NAME>" "<CTS_NUMBER>"
```
