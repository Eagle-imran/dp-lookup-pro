# 🚀 FEATURES_PLANNED.md — Roadmap for `dp-lookup-pro`

> **Roadmap for `dp-lookup-pro`.** Items shipped in v3.7.0–v3.10.0 are marked ✅ below;
> see [CHANGELOG.md](CHANGELOG.md) for what each one actually did.

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

### 3.2. ✅ SHIPPED (v3.7.0) — CRZ Sub-tier Specificity
* ~~Provide exact CRZ restriction tier classification rather than generic binary status.~~
* **Delivered**: `crz_status` now reports the sub-tier, e.g. `YES (CRZ II)`, read from the `category`/`CLASS` attribute of layers 14/1264/1548. This arrived alongside the fix for a false negative that had CRZ reading `NO` on every plot in Mumbai.

### 3.3. Civil Aviation Obstacle Limitation Funnel Check
* Query Civil Aviation height restriction funnels around Mumbai International Airport (BOM) and Juhu Aerodrome to flag maximum permissible building height AMSL (Above Mean Sea Level).

### 3.4. Railway Setback & Infrastructure Buffers
* **30m Railway Safety Buffer**: Flag 30-meter safety setback requirements if plot abuts Western, Central, or Harbour railway tracks.
* **High-Tension Line & Sewer Buffer**: Query high-tension power line corridors and major Nallah / sewer setback buffers.

---

## ⚡ 4. Speed & Computational Performance Optimizations

### 4.1. Local Spatial Cache — 📋 **SPECCED**, ready to build
> **Full spec: [SPEC-LOCAL-SPATIAL-CACHE.md](SPEC-LOCAL-SPATIAL-CACHE.md).** The
> original proposal below is kept for the record; two of its numbers were measured
> against the live server on 2026-07-30 and were wrong.

* **⚠️ Corrections to the original estimates**:
  * Mumbai has **135,337** parcels on layer 13, not ~15,000 (`returnCountOnly`).
  * A pre-baked file is **~90 MB** (geometry + 5 attributes + R-Tree) or **~126 MB**
    with all 33 fields — not 18–25 MB. Measured from 400 real WORLI parcels: median
    189 B of WKB geometry, median 11 vertices. It cannot be shrunk by simplifying,
    because the DXF's 4.6 cm dimensional accuracy is the product promise.
  * Bulk extraction is **easy**, not hard: `maxRecordCount: 50000` with pagination.
* **Revised shape**: cache **grows as the tool is used** rather than shipping
  pre-baked — 0 MB installed, no redistribution question. A per-village opt-in
  pre-bake is Phase 2.
* **The governing rule**: geometry is cached, **planning status is always live**.
  Layer 13 carries geometry and identity but no zone, reservation, CRZ or DP
  modification. Caching status is how you ship a confident wrong answer.
* **The real prize is correctness, not speed**: adjoining parcels are currently found
  with 4 fixed point-probes — a guess. An R-Tree plus shapely gives actual adjacency,
  which is what amalgamation studies depend on.
* **Honest speed impact**: the parcel fetch is the one *sequential* request, so
  removing it is real — but the answer still cannot beat the planning identify, which
  measures 414 ms–4,470 ms. Roughly 500 ms off a 900–5,000 ms answer.
* **No new dependencies**: `sqlite3` R-Tree is in the stdlib and `shapely` is already
  a dependency. SpatiaLite is explicitly rejected — a native library works against the
  "simple install" goal.

### 4.2. ✅ SHIPPED (v3.10.0) — Non-Blocking Document Pipeline
* **Delivered differently, and better**: rather than detaching background threads (which risks a killed process leaving a half-written bundle), the *wait* is split. All 25 requests still dispatch at once, but only the planning half is awaited before reporting. GeoJSON/DXF/KML are written in that half too, since they need geometry only.
* **Measured (WORLI 733 ×3)**: answer at 4,746 / 700 / 635 ms against totals of 6,246 / 6,470 / 6,443 ms — **1.3× / 9.2× / 10.1×**. Typically ~10×.
* **⚠️ Correction to an earlier assumption**: the map export is *not* reliably 95% of runtime. It is the slowest single call (5.6–5.9 s), but identify calls range 414 ms–4,470 ms, and the fast half is only as quick as its slowest call.

### 4.3. Pre-Stitched Satellite Base Tile LRU Cache (~400ms Savings)
* **Base Map Cache**: Maintain an LRU (Least Recently Used) disk cache of pre-stitched satellite base map tiles in `./output/.tile_cache/`.
* **Speed Impact**: Satellite aerial view generation drops from **~450 ms down to ~15 ms**.

---

## 🪙 5. Token & Context Efficiency Enhancements

### 5.1. Selective Output Granularity Flags (`--slim`, `--cad-only`)
> Partly addressed: `--json` and the readable summary already exist (v3.9.0), and the
> split pipeline means planning data arrives without waiting on documents.
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
| **Phase 3 (Regulatory)** | Heritage Layer 1540, ✅ CRZ Tiering, Aviation Funnel | Complete legal & environmental due-diligence | Enhanced risk management |
| **Phase 4 (Speed)** | 📋 Local spatial cache, ✅ Split-wait pipeline | Answer without waiting on imagery; **computed** adjacency instead of 4 probes | ✅ **Answer ~0.7s**, → ~0.2–0.5s warm |
| **Phase 5 (Tokens)** | `--slim` & `--cad-only` execution flags | Context window optimization | **~150 tokens per query** |

---

---

## 🔭 Next up (as of v3.12.0)

0. **Local spatial cache** — 📋 specced and ready to build: [SPEC-LOCAL-SPATIAL-CACHE.md](SPEC-LOCAL-SPATIAL-CACHE.md). Replaces the 4-probe neighbour guess with computed adjacency, and takes the one sequential network hop off the critical path. No new dependencies, ships at 0 MB.
1. **Basic FSI / buildable area** — permissible basic FSI from zone, plot area and road width. Scope to *basic* FSI only and label it indicative; the incentive regulations (33(7)/33(10)/33(11)) are legally intricate and a wrong buildable-area figure is worse than none.
   > ⚠️ **Blocked on the area question.** MCGM's record and MCGM's own digitised polygon disagree by 6.10% on AMBIVALI 807 and −7.82% on BANDRA-A 409, and the Property Card is a third figure again. FSI computed off an unreconciled plot area is wrong by that margin before any regulation is applied. Decide which area governs before building this.
2. **Web app with logins** — the commercialisation path. `lookup_plot_pro` is already standalone and importable, so a service can wrap it directly.
3. **Road probe tuning** — 9 probes means more chances to draw a slow request. Needs measuring against road-detection accuracy, not guessing.
4. **Multi-ring plots** — `export_dxf` treats every ring as an outer boundary, so a plot with an interior hole would have that ring's setback offset the wrong way. None seen in 14 samples.
