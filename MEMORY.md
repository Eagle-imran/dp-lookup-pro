# 🧠 MEMORY.md — MCGM DP 2034 Spatial Lookup Pro (`dp-lookup-pro`)

> **Comprehensive Project History, Architecture Reference, Technical Decisions, Performance Benchmarks & Integration Sitemap**

---

## 📌 Executive Project Summary

* **Project Name**: `dp-lookup-pro`
* **Repository**: [https://github.com/Eagle-imran/dp-lookup-pro](https://github.com/Eagle-imran/dp-lookup-pro)
* **Local Workspace Path**: `/Users/imranpatel/Developer/dp-lookup-pro-IP`
* **Primary Executable**: `./dp-lookup-pro`
* **Skill Metadata File**: `SKILL.md`
* **Purpose**: Automated Real Estate Spatial Querying, GIS CAD Exporter & DP Remark Docket Generator for Mumbai Land Parcels under MCGM Development Plan (SDP) 2014-34.

---

## 🛠️ Complete Technical Stack

| Layer / Subsystem | Technology | Description & Usage |
| :--- | :--- | :--- |
| **Language & Runtime** | Python `3.9` – `3.14+` | Core asynchronous execution environment (Tested & verified on Python 3.14). |
| **Package Manager** | `uv` | Rust-powered ultra-fast package & virtual environment manager (`pyproject.toml`, `uv.lock`). |
| **Async Networking** | `httpx[http2]` | HTTP/2 multiplexed connection pool (`max_keepalive_connections=30`, `max_connections=50`). |
| **Concurrency Engine** | `asyncio` | Single-batch concurrent request dispatching (`asyncio.gather`) and background CPU thread offloading (`asyncio.to_thread`). |
| **GIS & Projections** | WGS84 (`EPSG:4326`) & Mercator | Spherical Mercator (`EPSG:3857/102100`) to WGS84 coordinate transformation algorithms. |
| **Canvas & Image Engine** | Pillow (PIL) | Retina HD DP 2034 map overlays with North Arrow ($N \uparrow$) and scale legend, plus 3x3 Esri tile stitching. |
| **Document Compiler** | ReportLab | 2-Page Executive PDF DP Remark Docket builder with dynamic flowables, tables, and status banners. |
| **CAD Exporters** | `ezdxf`, GeoJSON, KML | Native AutoCAD `.dxf` drawing files, OGC `.geojson` vectors, and 3D Google Earth `.kml` placemarks. |
| **QR Code Engine** | `qrcode` | Dynamic scannable QR code linking physical PDF reports directly to live MCGM Web GIS Maps. |
| **Audit Database** | `openpyxl` | Appends query audit records to central Excel workbook (`output/dp-lookups.xlsx`). |
| **Persistent Caching** | Local JSON Store | Disk store at `<output_dir>/.cache_store.json`, 30-day TTL, `--no-cache` bypass. Verifies the bundle files still exist before serving, reports `cache_age_days` on every hit, and never caches a degraded run. |

---

## 📜 Key Problems Solved & Evolution History

### 1. 🌊 Coastal Regulation Zone (CRZ) Precision Fix
* **Issue**: General district boundary Layer `2238` (*Coastal Districts having CRZ*) was causing every land parcel in Mumbai City and Suburban districts to incorrectly report `CRZ Status: YES`.
* **Resolution**: Filtered CRZ queries strictly to plot-specific restriction layers (`[31, 1118, 2212, 2213, 2214, 2240, 2241, 2242, 2243]`). Excluded Layer 2238.

### 2. 🛰️ Satellite Aerial Engine Refactoring
* **Issue**: Direct Esri MapServer export server endpoints (`services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export`) threw HTTP 500 errors when queried with unaligned bounding boxes.
* **Resolution**: Replaced with standard XYZ tile fetching (`server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/18/{y}/{x}`) stitched into a seamless 3x3 grid canvas via Pillow at Zoom Level 18.

### 3. ⚡ Single-Batch HTTP/2 Async Concurrency
* **Issue**: Sequential API querying caused fresh lookups to take 3.5 – 5.0 seconds.
* **Resolution**: Pipelined all 18 network tasks (Identify, DP Map Export, 7 Road Queries, 5 Neighbor Identifies, 9 Satellite Tiles) into a single `asyncio.gather` execution block over HTTP/2 connection pooling.

### 4. 📁 Query-Specific Bundle Folder Isolation
* **Issue**: Flat output files in `./output/` created file collisions when multiple plots were queried.
* **Resolution**: Every query creates a clean, dedicated subfolder (`./output/<village_clean>_cts_<cts_clean>/`) containing all 6 generated export files.

### 5. 📐 Native AutoCAD `.dxf` Drawing Exporter
* **Issue**: Users required direct AutoCAD drawing files without needing manual GeoJSON conversion.
* **Resolution**: Integrated `ezdxf` to output native AutoCAD `.dxf` files with pre-styled layers (`PLOT_BOUNDARY` in Red, `ANNOTATION` in Cyan) and plot text metadata placed at the centroid.

---

## ⚡ Performance Benchmarks

| Query Execution Mode | Latency (ms) | Notes |
| :--- | :--- | :--- |
| **Repeat CLI Query (Persistent Disk Cache)** | ⚡ **`12.0 ms`** | Served instantly from `./output/.cache_store.json` |
| **Cold Fresh Network Query** | **`6,900 ms – 13,000 ms`** | 25 requests, tile stitching, PDF & CAD export. Measured 2026-07-28; earlier sub-second figures were not reproducible. |

---

## 📊 Structured JSON Output Specification (6 Sections)

```json
{
  "plot_identity": {
    "village": "BYCULLA",
    "cts_no": "1605",
    "ward": "E",
    "type": "CTS",
    "area_sqm": 1877.87,
    "coordinates_wgs84": {
      "latitude": 18.972385,
      "longitude": 72.82255
    }
  },
  "planning_remarks": {
    "status_badge": "🟡 MODIFIED (DP Notification Order)",
    "status_summary": "Modified via MCP/7526 dtd.22.08.2024",
    "zone": "R",
    "reservation": { "code": "None", "type": "None" },
    "designation": { "code": "EH1.2", "description": "Municipal Hospital" },
    "dp_modification": {
      "approval_no": "MCP/7526 dtd.22.08.2024",
      "details": "Existing Amenity of Municipal Hospital (EH1.2)...",
      "document_link": "https://dpremarks.mcgm.gov.in/..."
    }
  },
  "regulatory_and_infrastructure": {
    "crz_status": "NO (Outside CRZ Buffer)",
    "metro_buffer": "YES (Metro Buffer Zone)",
    "abutting_road": {
      "name": "DR ANANDRAO L NAIR RD",
      "width": "45.72 M"
    }
  },
  "spatial_cluster": {
    "adjoining_plots_count": 3,
    "adjoining_cts_plots": [
      { "cts_no": "1604", "village": "BYCULLA", "area_sqm": "888.98" }
    ]
  },
  "export_files": {
    "bundle_folder": "./output/byculla_cts_1605",
    "pdf_report": "./output/byculla_cts_1605/dp_report_E_1605_byculla.pdf",
    "hd_dp_map": "./output/byculla_cts_1605/plot_E_1605_byculla_hd.png",
    "satellite_view": "./output/byculla_cts_1605/plot_E_1605_byculla_satellite.png",
    "autocad_dxf": "./output/byculla_cts_1605/plot_E_1605_byculla.dxf",
    "autocad_geojson": "./output/byculla_cts_1605/plot_E_1605_byculla.geojson",
    "google_earth_kml": "./output/byculla_cts_1605/plot_E_1605_byculla.kml",
    "master_excel_register": "./output/dp-lookups.xlsx"
  },
  "metadata": {
    "source": "MCGM SDP 2014-34",
    "lookup_datetime": "2026-07-28 00:37:59",
    "execution_time_ms": 12.0,
    "cached_result": true,
    "interactive_web_map": "https://mcgm.maps.arcgis.com/..."
  }
}
```

---

## 🤖 Universal AI Harness Invocation Quick Reference

| Agent Harness | Invocation Command / Method |
| :--- | :--- |
| **Google Antigravity CLI** | `/dp-lookup-pro <VILLAGE_NAME> <CTS_NUMBER>` |
| **Claude Code (Anthropic)** | Ask Claude: *"Run DP lookup for Worli CTS 748A"* or `./dp-lookup-pro WORLI 748A` |
| **OpenAI Codex / Python LLMs** | `from cts_dp_lookup_pro import lookup_plot_pro` |
| **Cursor / Windsurf / Roo Code** | Terminal execution `./dp-lookup-pro "<VILLAGE_NAME>" "<CTS_NUMBER>"` |

---

## 📄 License & Data Attribution

* **Data Source**: Official Municipal Corporation of Greater Mumbai (MCGM) Development Plan 2034 ArcGIS REST Services (`agsmaps.mcgm.gov.in`).
* **Satellite Base Map**: Esri World Imagery (`services.arcgisonline.com`).
* **License**: **Proprietary — © 2026 Imran Patel. All rights reserved.** Not open-source. Evaluation use only; commercial licensing available on request. See `LICENSE`.
