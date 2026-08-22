# 🏛️ MCGM DP 2034 Spatial Lookup Pro (`dp-lookup-pro`)

> **Automated Real Estate Spatial Query, GIS CAD Exporter & DP Remark Docket Generator for Mumbai Land Parcels (MCGM SDP 2014-34)**

### 👉 New here? Read **[START-HERE.md](START-HERE.md)** instead.

**[START-HERE.md](START-HERE.md)** is the plain-English guide — what this does, what
you get, and a 5-minute setup. No technical background needed.
The rest of this README is the technical reference for developers.

> ⚖️ **Proprietary software** — © 2026 Imran Patel. All rights reserved. Not open-source.
> Free for personal evaluation; commercial use requires a licence. See [LICENSE](LICENSE).

**v3.14.0** · [Architecture](docs/ARCHITECTURE.md) · [Planning evidence](docs/PLANNING_EVIDENCE.md) · [Certified sources](docs/CERTIFIED_SOURCES.md) · [ArcGIS layer audit](docs/ARCGIS_LAYER_AUDIT.md) · [What changed](docs/CHANGELOG.md) · [Reading the DXF](docs/DXF-GUIDE.md) · [How to roll back](docs/ROLLBACK.md) · [System flow map](docs/APP_FLOW.html)

---

`dp-lookup-pro` is an enterprise-grade AI agent skill and standalone CLI tool that queries the official **MCGM Development Plan (DP) 2034 MapServer** to instantly retrieve zoning, land reservations, modification orders, CRZ restrictions, Metro rail buffers, road access widths, and adjoining plot clusters for any City Survey (CTS/CS) land parcel in Mumbai.

It automatically generates a complete export bundle containing an **Interactive HTML Map Dossier**, **2-Page PDF DP Remark Docket**, **Retina HD DP Maps**, **Tile-Stitched Satellite Aerial Views**, **AutoCAD DXF Drawing Files**, **QGIS GeoJSON**, and **Google Earth 3D KML** files.

---

## ✨ Features & Capabilities

* **🏷️ Automated Planning Status Badges**: Instantly classifies land parcels into `🟢 CLEAR (No Reservation)`, `🟡 MODIFIED (DP Order)`, or `🔴 RESERVED (DCPR Amenity)`.
* **🌐 Standalone Interactive HTML Map Dossier**: Self-contained offline GIS web dossier with 1-click Satellite/Cadastral switcher, net developable envelope, and HUD dashboard.
* **🌊 Precise CRZ & Infrastructure Detection**: Queries CRZ **zone polygons** (layers 14/1264/1548) and reports the sub-tier — `YES (CRZ II)`, not a bare yes — plus Layer 1550 Metro Rail Influence buffers.
* **🗺️ Village name help**: `--list-villages` lists all 128 valid names, and a wrong name suggests the right one (`BANDRA` → `BANDRA-A`…). 
* **📖 Readable output**: a plain summary by default; `--json` for the full response.
* **🗺️ Dual High-Definition Visuals**:
  * **Retina HD DP 2034 Map**: High-resolution zoning map complete with North Arrow ($N \uparrow$) and scale legend.
  * **Tile-Stitched Satellite Aerial View**: Pixel-aligned Esri World Imagery satellite view showing actual building structures and ground coverage.
* **🏘️ Adjoining CTS Plot Cluster Identification**: Identifies neighboring land parcels and their areas for site amalgamation and layout analysis.
* **🗃️ Audited local source database**: Keeps complete, independently versioned parcel and planning-layer snapshots in one SQLite file. Normal CLI lookup uses active local data first, records its snapshot provenance, and falls back visibly to live MCGM when local data is missing, stale, or invalid.
* **🔎 Plot Intelligence & Site Search**: Builds one verified record per unique village/CTS identity for instant dossiers, citywide filtering and side-by-side site comparison, with every fact linked to its source snapshot, layer and ObjectID.
* **📐 Native AutoCAD CAD & Google Earth Exports**:
  * **`.dxf`**: Native AutoCAD Drawing file ready to double-click and open instantly in **AutoCAD, AutoCAD LT, Civil 3D, and TurboCAD**! Includes layer styling & text annotations.
  * **`.geojson`**: Scale-accurate WGS84 (`EPSG:4326`) polygon for QGIS and ArcGIS.
  * **`.kml`**: Interactive 3D polygon with metadata popups for Google Earth.
* **📄 2-Page Executive PDF Report Docket**: Professional PDF containing metadata tables, status banners, maps, adjoining parcel lists, and a scannable QR Code linking directly to the live MCGM Web Map.
* **📊 Centralized Excel Register**: Automatically appends query results to `output/dp-lookups.xlsx`.
* **⚡ High-Speed Concurrency & Persistent Disk Cache**:
  * Requests pipeline concurrently through a bounded async pool with verified TLS, connection reuse, timeouts, and retry/backoff.
  * A cold lookup writes all seven bundle artifacts in **5–13 s**; the shared Excel register is updated alongside them.
  * Cached repeat queries return in **~0.4 s** end-to-end. Entries live **30 days**, self-invalidate if files are missing, and report cache age. Pass `--no-cache` to ignore an existing entry and fetch fresh data; a complete refreshed result becomes the new cache entry.

---

## 📋 Prerequisites & Compatibility

Before running `dp-lookup-pro`, ensure your environment meets the following requirements:

### 1. System Requirements
* **Operating System**: macOS, Linux, or Windows (WSL / PowerShell)
* **Python**: Python `3.9` up to `3.14+` *(Tested & verified on Python 3.14)*

### 2. Recommended Package Manager
* [uv](https://github.com/astral-sh/uv) (Fastest Python package manager, recommended):
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

---

## 🚀 Step-by-Step Walkthrough: From Setup to Final Output

Follow these 5 simple steps to set up, run, and inspect your DP Spatial Remark package:

### Step 1: Clone the Repository
Open your terminal and clone the repository:
```bash
git clone https://github.com/Eagle-imran/dp-lookup-pro.git
cd dp-lookup-pro
```

### Step 2: (Optional) Install as a command
```bash
uv pip install -e .
```
This provides a `dp-lookup-pro` command that works from any folder. You can skip
this and use `uv run python dp-lookup-pro ...` instead.

### Step 3: Install Dependencies
Automatic installation using `uv`:
```bash
uv sync
```
*(Alternatively, using standard Python `pip`):*
```bash
pip install "httpx>=0.28.0" pillow openpyxl reportlab qrcode ezdxf shapely
```

### Step 4: Execute a Plot Lookup Query
Run the command by passing the **Village Name** and **CTS Number**:
```bash
uv run python dp-lookup-pro WORLI 748A
```

The compatibility default uses the established layer set. Request the curated
due-diligence register explicitly when needed:

```bash
uv run dp-lookup-pro COLABA 1/600 --evidence standard --no-cache --json
uv run dp-lookup-pro "VILE PARLE" 1449 --evidence full --no-cache --json
```

See [Planning evidence](docs/PLANNING_EVIDENCE.md) for `basic`, `shadow`,
`standard`, and conditional `full` mode semantics.
*(The answer appears in about a second; the PDF, maps and CAD files finish a few seconds later. A cached lookup is instant. See [docs/CHANGELOG.md](docs/CHANGELOG.md).)*

### Step 5: Inspect the Generated Output Bundle
Navigate to the newly created subfolder `./output/worli_cts_748A/` to access all generated assets:

* 📐 **AutoCAD DXF**: Double-click `plot_G-S_748A_worli.dxf` to open directly in **AutoCAD / AutoCAD LT**!
* 📄 **PDF Docket**: Open `dp_report_G-S_748A_worli.pdf` to view the 2-page print-ready DP Remark docket.
* 📸 **Satellite View**: View `plot_G-S_748A_worli_satellite.png` to inspect building coverage & boundaries.
* 🗺️ **Retina HD DP Map**: View `plot_G-S_748A_worli_hd.png` to check zoning & road widths.
* 🌍 **Google Earth 3D**: Double-click `plot_G-S_748A_worli.kml` to launch interactive 3D mapping in Google Earth.
* 🌐 **QGIS / ArcGIS**: Import `plot_G-S_748A_worli.geojson` into GIS software for spatial analysis.
* 📊 **Excel Register**: Open `output/dp-lookups.xlsx` to review the master query log.

### Optional: build the local source database

For internal and repeated work, the repository includes a reliable local copy
of MCGM's parcel layer and 52 audited planning layers. Both datasets live in one
SQLite file but have separate versions, verification, activation and rollback.
This is separate from the 30-day report cache and is not checked into Git. Each
builder starts from the complete source ObjectID inventory, commits bounded
batches atomically, preserves the official attributes and geometry, resumes a
matching interrupted build, and refuses to activate an incomplete result.

Build and review a database explicitly. The shorter `db` commands use
`DP_LOOKUP_DATABASE`, then `data/mcgm-layer13.sqlite`, unless `--database` is
supplied:

```bash
dp-lookup-pro db parcels build
dp-lookup-pro db parcels status
dp-lookup-pro db parcels verify
dp-lookup-pro db parcels activate

dp-lookup-pro db planning build
dp-lookup-pro db planning status
dp-lookup-pro db planning verify
dp-lookup-pro db planning activate
```

Before downloading a new six-month snapshot, run the read-only checks:

```bash
dp-lookup-pro db health
dp-lookup-pro db check-upstream
dp-lookup-pro db check-upstream --json > docs/audits/upstream-check.json
```

`health` audits the local SQLite file, active snapshots, inventory equality,
planning registry, derived intelligence and optional enrichment. It performs no
network requests. `check-upstream` downloads only ArcGIS metadata, edit signals
and ObjectID inventories—never geometry. A changed or unknown result recommends
a staged build; it never activates or replaces data. Matching fingerprints are
strong operational evidence but not proof that coordinates under an existing
ObjectID are unchanged, so an annual forced full rebuild remains recommended.
The original flat `database build` and `database build-planning` forms remain
supported for existing scripts. The first live validation is preserved in the
[database maintenance audit](docs/audits/DATABASE-MAINTENANCE-CHECK-2026-08-23.md).

Complete parcel and planning snapshots were built, verified, sampled against
the live source, and activated on 2026-08-21. The current database is about
1.0 GiB and contains 135,342 parcel records plus 65,604 records across 52
planning layers. It remains ignored by Git and is not bundled with the package.
Normal CLI lookup uses it automatically when available:

```bash
dp-lookup-pro lookup WORLI 733
# Explicit form recommended for agents and new scripts.

dp-lookup-pro WORLI 733
# Historical short form remains fully supported.
# auto: local MCGM cadastral parcel snapshot first, live service fallback

dp-lookup-pro WORLI 733 --source local --database data/mcgm-layer13.sqlite
dp-lookup-pro WORLI 733 --source auto --database data/mcgm-layer13.sqlite
dp-lookup-pro WORLI 733 --source live
```

`local` requires active local parcel and planning snapshots. `auto` uses each
active local snapshot first and falls back visibly when it cannot answer. A
parcel snapshot older than 210 days remains usable with a warning; stale
planning falls back live in `auto` because planning status is more sensitive to
change. `auto` is the CLI default; `DP_LOOKUP_DATABASE` or `--database` can
override the database path.
Explicit `live` remains the verification escape hatch. Parcel identity,
neighbours, zoning, reservations, designations, DP modifications, CRZ, Metro
influence, optional planning evidence and road access are local-first. Live road
probes remain the fallback; the rendered DP map and satellite imagery remain
live. See the [local
snapshot specification](docs/SPEC-LOCAL-SPATIAL-CACHE.md) and [planning snapshot
contract](docs/PLANNING_SNAPSHOT.md) for validation and lifecycle details.

### Certified-source registry

When you receive a Property Card, certified CTS/Final Plot plan, measurement
record, licensed survey, or official DP Remarks plan, register it alongside the
snapshots. The registry is additive: it keeps the original MCGM parcel and
planning records untouched, while preserving every supplied file, checksum,
version and review event.

```bash
dp-lookup-pro evidence add evidence/worli-733.json --actor imran
dp-lookup-pro evidence verify 12 --reviewed-by imran
dp-lookup-pro evidence recommend WORLI 733
dp-lookup-pro evidence activate 12 --purpose geometry --activated-by imran --reason "accepted boundary evidence"
```

Activation is explicit and purpose-specific (`area`, `geometry`, or
`planning`). Normal lookup uses only active selections. Equal-ranked sources
are reported as a conflict until a person resolves them. A source change
invalidates the affected report-cache and plot-intelligence fingerprints. See
[Certified sources](docs/CERTIFIED_SOURCES.md) for the manifest format and
complete lifecycle.

### Build and query plot intelligence

The derived intelligence layer contains one record for each of the 119,519
queryable village/CTS identities in the active source snapshot. It is versioned
independently and cannot be activated unless every selected identity was
processed and its source versions match the active source snapshots.

```bash
# Validate the pipeline with a non-publishable sample
dp-lookup-pro plots build --limit 25 --json

# Complete resumable publication build
dp-lookup-pro plots build
dp-lookup-pro plots verify
dp-lookup-pro plots activate

# Real workflow commands
dp-lookup-pro plots analyze WORLI 733 --json
dp-lookup-pro plots search \
  --zone R --min-area 2000 --has-reservation no --max-encumbered 10
dp-lookup-pro plots compare WORLI:733 COLABA:1/600 --json
dp-lookup-pro plots check
```

This is an internal operational system of record, not a replacement for MCGM
or statutory/title documents. The complete lifecycle, refresh runbook and area
quality rules are in [Plot intelligence](docs/PLOT_INTELLIGENCE.md).

### Plot-area terminology

Reports keep two area facts visible instead of silently choosing one:

- **Recorded plot area** is the area value stored in the MCGM cadastral parcel
  record.
- **Calculated boundary area** is calculated from the polygon coordinates
  supplied with that record.
- **Area difference** shows how far those two values disagree.

The user-facing source label is **MCGM cadastral parcel record**. The ArcGIS
layer number remains available in technical provenance and audit logs, but is
not used as the primary description of the data.

---

## 🔐 Security, Permissions & System Requests

When invoking `dp-lookup-pro` inside AI Agent environments (e.g. Google Antigravity CLI, Claude Code, Cursor, Windsurf), the AI assistant will request explicit user approval for specific actions:

| Action / Permission | Why it is Requested | Target Resource / Scope |
| :--- | :--- | :--- |
| **1. File Read & Write (`write_file` / `read_file`)** | Creating `./output/<query_folder>/` to write PDFs, PNG maps, DXF drawings, GeoJSON, KML, and Excel logs. | Local directory `./output/*` |
| **2. Terminal Execution (`command`)** | Running the lookup. | `uv run python dp-lookup-pro` |
| **3. Web Requests (`read_url` / HTTP GET & POST)** | Fetching plot boundaries, CRZ layers, & satellite tiles from official GIS servers. | `https://agsmaps.mcgm.gov.in/*`<br>`https://server.arcgisonline.com/*` |

> **Note on Security & Privacy**: `dp-lookup-pro` **only** makes outbound HTTP requests to official government MapServers (`mcgm.gov.in`) and Esri basemaps (`arcgisonline.com`). It does **not** upload or transmit any local data or credentials.

---

## 🤖 Beginner-Friendly Guide: How to Use this Skill Across AI Harnesses

This repository conforms strictly to the **Agent Skill Specification (`SKILL.md`)** and can be loaded into any AI assistant or agent framework.

---

### 1. 🟢 Google Antigravity CLI / IDE
If you are using Google Antigravity AI assistant:
* **Option A (Workspace Skill)**: Keep this folder inside your active workspace. Antigravity will automatically detect `SKILL.md`.
* **Option B (Global Skill)**: Copy the repository into your global skills directory:
  ```bash
  cp -r . ~/.gemini/antigravity-cli/skills/dp-lookup-pro
  ```
* **Invocation**:
  * Type slash command: `/dp-lookup-pro BANDRA-A 409`
  * Or ask naturally: *"Check DP Remarks and generate PDF report for Bandra-A CTS 409"*

---

### 2. 🟠 Claude Code (Anthropic CLI)
If you are using Claude Code in your terminal:
1. Clone or link the repository into your project directory.
2. Open Claude Code in your terminal:
   ```bash
   claude
   ```
3. Ask Claude to execute the skill:
   > *"Run the DP lookup tool for Worli CTS 748A"*

   Claude Code runs `uv run python dp-lookup-pro WORLI 733` and reports the result, then points you at the generated PDF and DXF.

---

### 3. 🔵 OpenAI Codex / Custom Python AI Agents (LangChain, LlamaIndex, AutoGen)
If you are building a custom Python agent with OpenAI Codex or Function Calling:
1. Import `lookup_plot_pro` directly in your Python code:
   ```python
   from cts_dp_lookup_pro import lookup_plot_pro
   import asyncio

   async def main():
       # Call tool programmatically
       result = await lookup_plot_pro(village="BANDRA-A", cts_number="409")
       
       # Print PDF report & DXF file path
       print("PDF Report generated at:", result["export_files"]["pdf_report"])
       print("AutoCAD DXF generated at:", result["export_files"]["autocad_dxf"])

   asyncio.run(main())
   ```
Pass `on_data=` to receive the planning result as soon as it is known — roughly
ten times sooner than waiting for the map image:

```python
def show(snapshot):          # metadata.documents_pending is True here
    print(snapshot["regulatory_and_infrastructure"]["crz_status"])

result = await lookup_plot_pro("WORLI", "733", on_data=show)   # returned dict is final
```

2. Or register it as an Agent Tool:
   ```python
   from langchain.tools import tool

   @tool
   async def run_mumbai_dp_lookup(village: str, cts_number: str) -> dict:
       """Queries MCGM DP 2034 zoning, reservations, CRZ status, and generates PDF/DXF/GeoJSON exports."""
       return await lookup_plot_pro(village, cts_number)
   ```

---

### 4. 🟣 Cursor / Windsurf / Roo Code / VS Code AI Extensions
If you are pair-programming in Cursor or Windsurf:
* Simply open your AI Chat panel (`Cmd+L` or `Ctrl+L`) and type:
  > *"Run a DP lookup for Malabar Hill CTS 518 and give me the summary"*

---

## 💻 Manual CLI Usage

You can also run the tool directly from any shell prompt without an AI agent:

### Syntax:
```bash
uv run python dp-lookup-pro "<VILLAGE_NAME>" "<CTS_NUMBER>" [OUTPUT_DIR] [options]
```

| Option | Effect |
| :--- | :--- |
| `--json` | full JSON response instead of the summary (clean on stdout) |
| `--no-cache` | ignore any cached report, refetch, and replace it after a complete run |
| `--evidence MODE` | select `basic`, `shadow`, `standard`, or conditional `full` planning evidence; default is `basic` |
| `--source MODE` | choose `auto` (default), `live`, or strict `local` parcel and planning sources |
| `--database PATH` | override auto's default SQLite path; required with strict `local` |
| `--list-villages` | print all 128 valid village names and exit |

Database administration is separate from plot lookup. The `database` flat
forms remain compatibility aliases:

```bash
dp-lookup-pro db health
dp-lookup-pro db check-upstream
dp-lookup-pro db parcels <build|status|verify|diff|activate|rollback>
dp-lookup-pro db planning <build|status|verify|activate|rollback>
```

### Examples:
```bash
# Example 1: Query Bandra plot (note: 'BANDRA' alone is not a valid village)
uv run python dp-lookup-pro BANDRA-A 409

# Example 2: Query Worli plot (coastal - reports CRZ II)
uv run python dp-lookup-pro WORLI 733

# Example 3: Query Malabar Hill plot with custom output folder
uv run python dp-lookup-pro "MALABAR HILL" 518 ./my_reports
```

---

## 📁 Output Folder & Bundle Structure

Each query creates a dedicated, self-contained bundle directory inside `./output/<village_name>_cts_<cts_no>/`:

```text
output/
├── dp-lookups.xlsx                             # Master Excel log register
└── <village_name>_cts_<cts_no>/                # Dedicated query export bundle
    ├── dp_report_<ward>_<cts_no>_<village>.pdf # 2-Page Executive PDF Remark Docket
    ├── plot_<ward>_<cts_no>_<village>_hd.png   # Retina HD DP 2034 Zoning Map Snapshot
    ├── plot_map_<ward>_<cts_no>_<village>.html # Standalone Interactive HTML Map Dossier
    ├── plot_<ward>_<cts_no>_<village>_satellite.png # High-Res Tile-Stitched Satellite View
    ├── plot_<ward>_<cts_no>_<village>.dxf      # Native AutoCAD Drawing File (.dxf)
    ├── plot_<ward>_<cts_no>_<village>.geojson  # QGIS / ArcGIS Spatial Polygon File
    └── plot_<ward>_<cts_no>_<village>.kml      # Google Earth 3D Interactive File
```

The query folder contains seven bundle artifacts (HTML, PDF, two PNG maps, DXF,
GeoJSON, and KML). The shared `output/dp-lookups.xlsx` register is maintained
at the output root, alongside the query folders.

---

## 📊 Sample JSON Response Structure

The tool outputs a structured, intuitive JSON object containing 6 logical sections:

```json
{
  "plot_identity": {
    "village": "<VILLAGE_NAME>",
    "cts_no": "<CTS_NUMBER>",
    "ward": "<WARD_LETTER>",
    "type": "CTS",
    "area_sqm": 1250.0,
    "area_source": "Recorded plot area",
    "coordinates_wgs84": {
      "latitude": 19.000000,
      "longitude": 72.800000
    }
  },
  "planning_remarks": {
    "status_badge": "🟢 CLEAR (No Reservation)",
    "status_summary": "Unreserved Land Parcel",
    "zone": "R",
    "reservation": { "code": "None", "type": "None" },
    "designation": { "code": "None", "description": "None" },
    "dp_modification": {
      "approval_no": "None",
      "details": "None",
      "document_link": "None"
    }
  },
  "regulatory_and_infrastructure": {
    "crz_status": "NO (Outside CRZ Buffer)",
    "metro_buffer": "NO",
    "abutting_road": {
      "name": "MAIN ROAD",
      "width": "18.30 M"
    }
  },
  "spatial_cluster": {
    "adjoining_plots_count": 3,
    "adjoining_cts_plots": [
      { "cts_no": "101", "village": "<VILLAGE_NAME>", "area_sqm": "850.00" },
      { "cts_no": "102", "village": "<VILLAGE_NAME>", "area_sqm": "920.00" }
    ]
  },
  "export_files": {
    "bundle_folder": "./output/<village_name>_cts_<cts_no>",
    "pdf_report": "./output/<village_name>_cts_<cts_no>/dp_report_<cts>.pdf",
    "hd_dp_map": "./output/<village_name>_cts_<cts_no>/plot_<cts>_hd.png",
    "satellite_view": "./output/<village_name>_cts_<cts_no>/plot_<cts>_satellite.png",
    "autocad_dxf": "./output/<village_name>_cts_<cts_no>/plot_<cts>.dxf",
    "autocad_geojson": "./output/<village_name>_cts_<cts_no>/plot_<cts>.geojson",
    "google_earth_kml": "./output/<village_name>_cts_<cts_no>/plot_<cts>.kml",
    "master_excel_register": "./output/dp-lookups.xlsx"
  },
  "metadata": {
    "source": "MCGM SDP 2014-34",
    "lookup_datetime": "2026-07-28 12:00:00",
    "execution_time_ms": 0.15,
    "cached_result": true,
    "complete": true,
    "warnings": [],
    "notes": [],
    "cache_age_days": 3.4,
    "cache_expires_in_days": 26.6,
    "interactive_web_map": "https://mcgm.maps.arcgis.com/..."
  }
}
```

---

## 📄 License & Data Attribution

* **Data Source**: Official Municipal Corporation of Greater Mumbai (MCGM) Development Plan 2034 ArcGIS REST Services (`agsmaps.mcgm.gov.in`).
* **Satellite Base Map**: Esri World Imagery (`services.arcgisonline.com`).
* **License**: **Proprietary — © 2026 Imran Patel. All rights reserved.** This is *not* open-source software. Free for personal evaluation and testing only; commercial use, redistribution and modification require written permission. See [LICENSE](LICENSE).
* **Disclaimer**: Output is **indicative only** — not an official DP Remark and not certified by MCGM. Always obtain an official DP Remark before making legal, financial or development decisions.
