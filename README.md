# 🏛️ MCGM DP 2034 Spatial Lookup Pro (`dp-lookup-pro`)

> **Automated Real Estate Spatial Query, GIS CAD Exporter & DP Remark Docket Generator for Mumbai Land Parcels (MCGM SDP 2014-34)**

### 👉 New here? Read **[START-HERE.md](START-HERE.md)** instead.

**[START-HERE.md](START-HERE.md)** is the plain-English guide — what this does, what
you get, and a 5-minute setup. No technical background needed.
The rest of this README is the technical reference for developers.

> ⚖️ **Proprietary software** — © 2026 Imran Patel. All rights reserved. Not open-source.
> Free for personal evaluation; commercial use requires a licence. See [LICENSE](LICENSE).

**v3.12.0** · [What changed](docs/CHANGELOG.md) · [Reading the DXF](docs/DXF-GUIDE.md) · [How to roll back](docs/ROLLBACK.md) · [System flow map](docs/APP_FLOW.html)

---

`dp-lookup-pro` is an enterprise-grade AI agent skill and standalone CLI tool that queries the official **MCGM Development Plan (DP) 2034 MapServer** to instantly retrieve zoning, land reservations, modification orders, CRZ restrictions, Metro rail buffers, road access widths, and adjoining plot clusters for any City Survey (CTS/CS) land parcel in Mumbai.

It automatically generates a complete export bundle containing a **2-Page PDF DP Remark Docket**, **Retina HD DP Maps**, **Tile-Stitched Satellite Aerial Views**, **AutoCAD DXF Drawing Files**, **QGIS GeoJSON**, and **Google Earth 3D KML** files.

---

## ✨ Features & Capabilities

* **🏷️ Automated Planning Status Badges**: Instantly classifies land parcels into `🟢 CLEAR (No Reservation)`, `🟡 MODIFIED (DP Order)`, or `🔴 RESERVED (DCPR Amenity)`.
* **🌊 Precise CRZ & Infrastructure Detection**: Queries CRZ **zone polygons** (layers 14/1264/1548) and reports the sub-tier — `YES (CRZ II)`, not a bare yes — plus Layer 1550 Metro Rail Influence buffers.
* **🗺️ Village name help**: `--list-villages` lists all 128 valid names, and a wrong name suggests the right one (`BANDRA` → `BANDRA-A`…). 
* **📖 Readable output**: a plain summary by default; `--json` for the full response.
* **🗺️ Dual High-Definition Visuals**:
  * **Retina HD DP 2034 Map**: High-resolution zoning map complete with North Arrow ($N \uparrow$) and scale legend.
  * **Tile-Stitched Satellite Aerial View**: Pixel-aligned Esri World Imagery satellite view showing actual building structures and ground coverage.
* **🏘️ Adjoining CTS Plot Cluster Identification**: Identifies neighboring land parcels and their areas for site amalgamation and layout analysis.
* **📐 Native AutoCAD CAD & Google Earth Exports**:
  * **`.dxf`**: Native AutoCAD Drawing file ready to double-click and open instantly in **AutoCAD, AutoCAD LT, Civil 3D, and TurboCAD**! Includes layer styling & text annotations.
  * **`.geojson`**: Scale-accurate WGS84 (`EPSG:4326`) polygon for QGIS and ArcGIS.
  * **`.kml`**: Interactive 3D polygon with metadata popups for Google Earth.
* **📄 2-Page Executive PDF Report Docket**: Professional PDF containing metadata tables, status banners, maps, adjoining parcel lists, and a scannable QR Code linking directly to the live MCGM Web Map.
* **📊 Centralized Excel Register**: Automatically appends query results to `output/dp-lookups.xlsx`.
* **⚡ High-Speed Concurrency & Persistent Disk Cache**:
  * **Answer in ~0.7 s.** All 25 requests fire at once, but only the planning half is awaited before reporting; the map, satellite and PDF finish after. Typically ~10× faster to an answer than waiting for everything (measured 0.7 s vs 6.5 s).
  * A cold lookup writes all six files in **5–13 s**. MCGM is slow and variable across every endpoint.
  * Cached repeat queries return in **~0.4 s** end-to-end (the lookup itself is sub-millisecond; the rest is Python interpreter startup). Entries live **30 days** — matching how slowly DP data actually moves — are invalidated automatically if their files are deleted, and report their age on every hit. Pass `--no-cache` for a same-day fresh check. The cache lives in the output directory and expires after 24 hours by default; pass `--no-cache` to force a fresh fetch.

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
pip install "httpx[http2]>=0.28.0" pillow openpyxl reportlab qrcode ezdxf
```

### Step 4: Execute a Plot Lookup Query
Run the command by passing the **Village Name** and **CTS Number**:
```bash
uv run python dp-lookup-pro WORLI 748A
```
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
| `--no-cache` | ignore any cached report and refetch |
| `--list-villages` | print all 128 valid village names and exit |

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
    ├── plot_<ward>_<cts_no>_<village>_sat.png  # High-Res Tile-Stitched Satellite View
    ├── plot_<ward>_<cts_no>_<village>.dxf      # Native AutoCAD Drawing File (.dxf)
    ├── plot_<ward>_<cts_no>_<village>.geojson  # QGIS / ArcGIS Spatial Polygon File
    └── plot_<ward>_<cts_no>_<village>.kml      # Google Earth 3D Interactive File
```

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
    "area_source": "approved (MCGM AREA_APP_SQ_MTRS)",
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
