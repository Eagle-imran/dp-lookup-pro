# 🧠 MEMORY.md — MCGM DP 2034 Spatial Lookup Pro (`dp-lookup-pro`)

> **Comprehensive Project History, Architecture Reference, Technical Decisions, Performance Benchmarks & Integration Sitemap**

---

## 📌 Executive Project Summary

* **Project Name**: `dp-lookup-pro`
* **Repository**: [https://github.com/Eagle-imran/dp-lookup-pro](https://github.com/Eagle-imran/dp-lookup-pro)
* **Local Workspace Path**: `/Users/imranpatel/Developer/dp-lookup-pro-IP`
* **Primary Executable**: `uv run python dp-lookup-pro` (or `dp-lookup-pro` after `uv pip install -e .`)
* **Current Version**: 3.10.0 — merged to `main` 2026-07-29 (`9bc0f2e`)
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
| **Geometry** | `shapely` | True parallel polygon offsetting for setback lines. A hand-rolled miter offset self-intersected on concave plots. |
| **CAD Exporters** | `ezdxf`, GeoJSON, KML | Native AutoCAD `.dxf` drawing files, OGC `.geojson` vectors, and 3D Google Earth `.kml` placemarks. |
| **QR Code Engine** | `qrcode` | Dynamic scannable QR code linking physical PDF reports directly to live MCGM Web GIS Maps. |
| **Audit Database** | `openpyxl` | Appends query audit records to central Excel workbook (`output/dp-lookups.xlsx`). |
| **Persistent Caching** | Local JSON Store | Disk store at `<output_dir>/.cache_store.json`, 30-day TTL, `--no-cache` bypass. Verifies the bundle files still exist before serving, reports `cache_age_days` on every hit, and never caches a degraded run. |

---

## 📜 Key Problems Solved & Evolution History

### 1. 🌊 Coastal Regulation Zone (CRZ) — two bugs, both now fixed
* **Bug 1 (false positive)**: District boundary Layer `2238` (*Coastal Districts having CRZ*) covers all of Mumbai City and Suburban, so every parcel reported `CRZ: YES`.
* **First attempt**: Swapped to `[31, 1118, 2212, 2213, 2214, 2240, 2241, 2242, 2243]`. This silenced the false positives — but **every one of those layers is a boundary LINE** (High Tide Line, Low Tide Line, CRZ Lines & Boundaries, Hazard Line).
* **Bug 2 (false negative, 2026-07-28)**: A point-identify at a plot centroid can never intersect a line, so the check became structurally incapable of returning `YES`. **Every plot in Mumbai reported `CRZ: NO`.** It looked correct precisely because it was silent.
* **Resolution**: Use the CRZ **zone polygons** `[14, 1264, 1548]`, reading the sub-tier from `category` / `Category` / `CLASS` to report `YES (CRZ II)`. Layer `2238` remains excluded.
* **Verified both directions**: coastal plots (WORLI 886/947, BANDRA-A 409) return `YES (CRZ II)`; inland plots (BYCULLA 1605, TARDEO 264) correctly stay `NO`.

### 2. 🛰️ Satellite Aerial Engine Refactoring
* **Issue**: Direct Esri MapServer export server endpoints (`services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export`) threw HTTP 500 errors when queried with unaligned bounding boxes.
* **Resolution**: Replaced with standard XYZ tile fetching (`server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/18/{y}/{x}`) stitched into a seamless 3x3 grid canvas via Pillow at Zoom Level 18.

### 3. ⚡ Single-Batch HTTP/2 Async Concurrency
* **Issue**: Sequential API querying caused fresh lookups to take 3.5 – 5.0 seconds.
* **Resolution**: Pipelined the network tasks over HTTP/2 pooling. **25 requests** per cold lookup: 1 parcel query (sequential) + 24 concurrent (1 identify, 1 map export, 9 road probes, 4 neighbour probes, 9 satellite tiles). Since v3.10.0 the *wait* is split in two — see history entry 10 — though all 25 still dispatch together.
* **Measured reality**: a cold lookup takes **5–13 s**. The `/export` map-image request is consistently the slowest single call (5.6–5.9 s), but it is **not** reliably 95% of runtime — an earlier note claiming that held for one measurement only. Identify calls range 414 ms–4,470 ms run to run. MCGM is slow *and variable* across every endpoint.
* **v3.10.0**: the wait is split. Planning data and vector exports complete in the fast half (~0.7 s typical), then the map, satellite and PDF finish. See history entry 10.

### 4. 📁 Query-Specific Bundle Folder Isolation
* **Issue**: Flat output files in `./output/` created file collisions when multiple plots were queried.
* **Resolution**: Every query creates a clean, dedicated subfolder (`./output/<village_clean>_cts_<cts_clean>/`) containing all 6 generated export files.

### 5. 📐 Native AutoCAD `.dxf` Drawing Exporter
* **Issue**: Users required direct AutoCAD drawing files without needing manual GeoJSON conversion.
* **Resolution**: Integrated `ezdxf` to output native AutoCAD `.dxf` files with pre-styled layers (`PLOT_BOUNDARY` in Red, `ANNOTATION` in Cyan) and plot text metadata placed at the centroid.

### 6. 🛣️ Road Detection — two dead queries (2026-07-28)
* **Issue**: Two `/query` calls against layers `193`/`194` sent a polygon geometry. Those layers have spatial querying disabled server-side and answer **HTTP 200 carrying `{"error":{"code":400}}`** for every geometry type. The parser read `.get('features', [])`, saw an empty list, and reported "no road". They had never worked.
* **Resolution**: Both removed. Road probes now sample the midpoints of the longest boundary edges **in addition to** the original centroid and bbox corners. MOHILI 732 went from `None` to `21.35 m`.
* **⚠️ Caution**: the probe sets are additive on purpose. An attempt that *replaced* the corner probes regressed WORLI 947.

### 7. 🤫 Silent Failure Elimination (2026-07-28)
* **Issue**: `return_exceptions=True` plus a 10 s timeout meant a slow server produced `zone='Unknown'`, `road=None`, 0 neighbours and `CRZ='NO'` — **and still wrote a PDF, appended to the Excel register, and cached it permanently.**
* **Root cause**: ArcGIS reports errors as HTTP 200 with an `error` key; `.get('features', [])` on such a body is indistinguishable from a genuine no-match. This one pattern caused three separate silent failures.
* **Resolution**: All parsing routed through `usable_json()`. A failed identify aborts the run. Partial failures become `metadata.warnings` with a `metadata.complete` flag, and are never cached. Timeout 10 s → 20 s.

### 8. 📐 Blank Plot Areas (2026-07-28)
* **Issue**: `AREA_APP_SQ_MTRS` is null for some parcels (MALABAR HILL 518, TARDEO 264), so area rendered blank.
* **Resolution**: Fall back to `SHAPE.AREA`, which is populated and already in true ground square metres (verified: matches exactly where both exist). Labelled via `plot_identity.area_source` — it is the *digitised* area, not the approved one, and the two differ by up to 7%.

### 9. 💾 Cache Policy (2026-07-28)
* **Issue**: no expiry, no bypass, stored failures permanently, ignored `output_dir`, and returned paths to files that no longer existed.
* **Resolution**: 30-day TTL (chosen from measured data velocity — layer 13 carries `LAST_EDITED_DATE 2019-01-23` on every parcel), `--no-cache` bypass, store at `<output_dir>/.cache_store.json`, bundle-file verification on every hit, and `cache_age_days` reported so staleness is never silent.
* **⚠️ Trap**: `LAST_EDITED_DATE` is identical across all parcels — it is the bulk load date, **not** a usable revalidation key. DP modifications do not appear on the parcel record either; they live in layer `192`.

### 10. ⚡ Split-Wait Pipeline (2026-07-29, v3.10.0)
* **Issue**: the answer waited on the map image, so a lookup that knew the zoning in 0.7 s stayed silent for 6.5 s.
* **Resolution**: all 25 requests still dispatch at once, but only the planning half is awaited before reporting — parcel, identify, roads, neighbours. GeoJSON/DXF/KML need geometry only, so they are written there too. `lookup_plot_pro(on_data=...)` fires with `metadata.documents_pending: True`; the returned dict is still final.
* **Measured (WORLI 733 ×3)**: answer at 4,746 / 700 / 635 ms against totals of 6,246 / 6,470 / 6,443 ms — **1.3× / 9.2× / 10.1×**. Typically ~10×.
* **⚠️ Caveat**: the fast half is only as quick as its slowest call. Run 1's outlier was a stalled identify, not the map.

### 11. 📐 Architect-Ready DXF (2026-07-28, v3.8.x)
* **Setbacks were not setbacks**: vertices were pulled toward the centroid, so the "3 m" line measured 1.15–3.00 m. Now a true parallel offset via `shapely`, exact at 3.000/6.000 m, omitted and labelled when a plot is too small.
* **Adjoining plots were drawn at ~8e11** — neighbour geometry arrives in Web Mercator but was treated as WGS84 degrees. Affected every DXF ever generated.
* **`C-ROAD-ALIGN` was always empty** — geometry was not requested, and road layers return mixed types (193/194 `paths`, 44/45 `rings`) where only `paths` was read. Roads are clipped to the plot vicinity; one arrived 3.8 km long.
* Added a layer legend, PLOT DATA panel, north arrow, and a sheet border sized from drawn content.

### 12. 📖 Readable Output & Village Help (2026-07-28, v3.9.0)
* CLI prints a plain summary instead of 60 lines of JSON (`--json` for raw, now clean on stdout). An LLM became optional rather than a workaround.
* `--list-villages` plus did-you-mean suggestions. `BANDRA` is not a valid village — the 128 names ship locally, so suggestions cost no network call.

---

## ⚡ Performance Benchmarks

| Query Execution Mode | Latency (ms) | Notes |
| :--- | :--- | :--- |
| **Answer visible (v3.10.0 fast half)** | **`~700 ms`** | Planning data + GeoJSON/DXF/KML. Typical; a slow identify can push this to ~4.7 s. |
| **Repeat Query (cache hit)** | **`~0.2 ms`** | In-process. ~390 ms for a full CLI run, dominated by Python startup. |
| **Cold Fresh Query (all 6 files)** | **`5,000 ms – 13,000 ms`** | 25 requests, tile stitching, PDF & CAD export. Highly variable server-side. |

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
    "area_source": "approved (MCGM AREA_APP_SQ_MTRS)",
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
    "execution_time_ms": 0.15,
    "cached_result": true,
    "complete": true,
    "documents_pending": false,
    "warnings": [],
    "notes": [],
    "cache_age_days": 3.4,
    "interactive_web_map": "https://mcgm.maps.arcgis.com/..."
  }
}
```

---

## 🤖 Universal AI Harness Invocation Quick Reference

| Agent Harness | Invocation Command / Method |
| :--- | :--- |
| **Google Antigravity CLI** | `/dp-lookup-pro <VILLAGE_NAME> <CTS_NUMBER>` |
| **Claude Code (Anthropic)** | Ask Claude: *"Run DP lookup for Worli CTS 733"* or `uv run python dp-lookup-pro WORLI 733` |
| **OpenAI Codex / Python LLMs** | `from cts_dp_lookup_pro import lookup_plot_pro` |
| **Cursor / Windsurf / Roo Code** | Terminal `uv run python dp-lookup-pro "<VILLAGE>" "<CTS>" [--no-cache]` |

---

## 📄 License & Data Attribution

* **Data Source**: Official Municipal Corporation of Greater Mumbai (MCGM) Development Plan 2034 ArcGIS REST Services (`agsmaps.mcgm.gov.in`).
* **Satellite Base Map**: Esri World Imagery (`services.arcgisonline.com`).
* **License**: **Proprietary — © 2026 Imran Patel. All rights reserved.** Not open-source. Evaluation use only; commercial licensing available on request. See `LICENSE`.
