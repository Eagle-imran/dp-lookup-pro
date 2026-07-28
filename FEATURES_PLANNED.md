# 🚀 FEATURES_PLANNED.md — Roadmap for `dp-lookup-pro`

> **Comprehensive Future Feature Roadmap for Real Estate Output Enhancements, Sub-Second Performance Optimizations, and Token Cost Reduction**

---

## 📌 Executive Summary

This roadmap outlines planned enterprise upgrades for **`dp-lookup-pro`** designed to make it the definitive GIS real estate spatial engine, urban feasibility calculator, and CAD deliverable generator for Mumbai (MCGM SDP 2014–34).

---

## 🏗️ 1. Output & Urban Feasibility Enhancements

### 1.1. DCPR 2034 FSI & BUA Feasibility Calculator
* **Permissible Basic FSI**: Automatically compute basic FSI based on plot zone (`R`, `C`, `I`), plot area, and abutting road width.
* **Additional / Premium FSI & TDR Eligibility**: Calculate max permissible FSI under DCPR 2034 Regulations:
  * **Reg 30(A)**: Standard TDR & Premium FSI loading based on road width (e.g. 9m, 12m, 18m, 27m+).
  * **Reg 33(7)**: Urban Society Redevelopment incentive FSI.
  * **Reg 33(10)**: Slum Rehabilitation Scheme (SRA) BUA multipliers.
  * **Reg 33(11)**: Affordable Housing incentive FSI.
* **Total Permissible Built-up Area (BUA)**: Output total potential construction area in both **sq. meters** and **sq. feet** ($\text{Area} \times \text{Max FSI}$).

### 1.2. Height & Setback Feasibility Scorecard
* Estimate minimum required open space setbacks (Front, Rear, Side) based on building height brackets and plot area under DCPR 2034 Table 18.

---

## 📄 2. Multi-Format Deliverables & Presentation Assets

### 2.1. Standalone Interactive HTML Web Report (`.html`)
* **Interactive Web Report**: Generate a self-contained single-file HTML web report (`dp_report_<WARD>_<CTS>_<VILLAGE>.html`).
* **Features**: Embedded Leaflet / Mapbox JS map with toggleable DP 2034 map / satellite layers, dark mode theme, interactive polygon popups, layer legends, and print-ready CSS (`@media print`).

### 2.2. Single-Click Zip Archive Bundle (`.zip`)
* **Auto-Archival**: Automatically compress all generated deliverables (`.pdf`, `.png`, `.dxf`, `.geojson`, `.kml`) into a single `.zip` file (`<village>_cts_<cts>_bundle.zip`) inside `./output/` for instant client delivery via email or API.

### 2.3. SVG Vector Graphic Export (`.svg`)
* **Vector Graphic Export**: Output high-resolution SVG vector maps (`plot_<WARD>_<CTS>_<VILLAGE>.svg`) for architectural presentation decks and vectorized graphic design software (Illustrator, Figma, Inkscape).

### 2.4. Dual-View 4K Split Composite Image (`.png`)
* **Side-by-Side Graphic**: Generate a single 4K side-by-side split canvas (`plot_<WARD>_<CTS>_<VILLAGE>_comparison.png`) displaying the **DP 2034 Zoning Map** alongside the **Esri Satellite View**, complete with aligned scale bars, legend, and North Arrow.

---

## ⚖️ 3. Regulatory & Environmental Compliance Scorecard

### 3.1. Heritage Structure & Precinct Clearance Check
* **Layer 1540 Query**: Automatically query MCGM Heritage Layer `1540` to flag proximity to Listed Heritage Buildings (Grade I, Grade II-A, Grade II-B, Grade III) or Heritage Precinct boundaries.

### 3.2. Coastal Regulation Zone (CRZ) Sub-tier Specificity
* Provide exact CRZ restriction tier classification (**CRZ-I(A)** Mangroves, **CRZ-I(B)** Intertidal, **CRZ-II** Developed urban shoreline, **CRZ-III**) rather than generic binary status.

### 3.3. Civil Aviation Obstacle Limitation Funnel Check
* Query Civil Aviation height restriction funnels around Mumbai International Airport (BOM) and Juhu Aerodrome to flag maximum permissible building height AMSL (Above Mean Sea Level).

### 3.4. Railway Setback & Infrastructure Buffers
* **30m Railway Safety Buffer**: Flag 30-meter safety setback requirements if plot abuts Western, Central, or Harbour railway tracks.
* **High-Tension Line & Sewer Buffer**: Query high-tension power line corridors and major Nallah / sewer setback buffers.

---

## ⚡ 4. Speed & Computational Performance Optimizations

### 4.1. Local Offline SQLite / DuckDB Spatial Database (~800ms Savings)
* **Pre-baked Database**: Package a local, pre-indexed SQLite/SpatiaLite database file (`./data/mumbai_sdp_2034.sqlite` — ~18 MB) containing all ~15,000 Mumbai CTS parcel boundaries and metadata.
* **Speed Impact**: Reduces initial parcel boundary lookup latency from **~500 ms (network call) down to ~2 ms (local SQLite query)**.

### 4.2. Asynchronous Non-Blocking Document Pipeline (~1.5s Savings)
* **Background Document Build**: Return the core JSON planning remarks, status badge, and regulatory data immediately to the LLM agent in **~1.2 seconds**, while spawning background thread tasks to finish writing the PDF report, DXF drawing, and Excel register.
* **Speed Impact**: Perceived fresh query latency drops from **~5.2 seconds down to ~1.2 seconds**.

### 4.3. Pre-Stitched Satellite Base Tile LRU Cache (~400ms Savings)
* **Base Map Cache**: Maintain an LRU (Least Recently Used) disk cache of pre-stitched satellite base map tiles in `./output/.tile_cache/`.
* **Speed Impact**: Satellite aerial view generation drops from **~450 ms down to ~15 ms**.

---

## 🪙 5. Token & Context Efficiency Enhancements

### 5.1. Selective Output Granularity Flags (`--slim`, `--full`, `--cad-only`)
* Add execution flags to tailor return payload size:
  * `--slim`: Returns minimal JSON summary (~150 tokens) for quick status checks.
  * `--full`: Default rich 6-section JSON response (~480 tokens).
  * `--cad-only`: Bypasses PDF and image generation, focusing purely on DXF CAD generation for maximum speed.

### 5.2. Delta Diff Tracking for Portfolio Bulk Queries
* When running batch lookups for multiple parcels, output a concise diff table showing changes in zoning, reservations, or modifications across parcels to minimize context window consumption.

---

## 📅 Roadmap Summary Matrix

| Milestone Phase | Feature Highlights | Primary Benefit | Target Latency / Token Impact |
| :--- | :--- | :--- | :--- |
| **Phase 1 (Feasibility)** | FSI & BUA Calculator, Height & Setback Scorecard | Direct urban feasibility numbers | 0 ms (Pure math calculations) |
| **Phase 2 (Deliverables)** | Interactive HTML Report, ZIP Bundle, SVG Vector | Client-ready presentation assets | Single-click delivery |
| **Phase 3 (Regulatory)** | Heritage Layer 1540, CRZ Tiering, Aviation Funnel | Complete legal & environmental due-diligence | Enhanced risk management |
| **Phase 4 (Speed)** | Local SQLite Database, Async Doc Pipeline | Sub-2 second cold network queries | **Fresh Query < 1.4s** |
| **Phase 5 (Tokens)** | `--slim` & `--cad-only` execution flags | Context window optimization | **~150 tokens per query** |

---

*File maintained by Antigravity AI Coding Assistant.*
