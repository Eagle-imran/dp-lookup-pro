# 🏛️ MCGM DP 2034 Spatial Lookup Pro (`cts-dplookup-pro`)

> **Automated Real Estate Spatial Query, GIS CAD Exporter & DP Remark Docket Generator for Mumbai Land Parcels (MCGM SDP 2014-34)**

`cts-dplookup-pro` is an enterprise-grade AI agent skill and standalone CLI tool that queries the official **MCGM Development Plan (DP) 2034 MapServer** to instantly retrieve zoning, land reservations, modification orders, CRZ restrictions, Metro rail buffers, road access widths, and adjoining plot clusters for any City Survey (CTS/CS) land parcel in Mumbai.

It automatically generates a complete export bundle containing a **2-Page PDF DP Remark Docket**, **Retina HD DP Maps**, **Tile-Stitched Satellite Aerial Views**, **AutoCAD/QGIS GeoJSON**, and **Google Earth 3D KML** files.

---

## ✨ Features & Capabilities

* **🏷️ Automated Planning Status Badges**: Instantly classifies land parcels into `🟢 CLEAR (No Reservation)`, `🟡 MODIFIED (DP Order)`, or `🔴 RESERVED (DCPR Amenity)`.
* **🌊 Precise CRZ & Infrastructure Detection**: Queries plot-specific Coastal Regulation Zone (CRZ-I/II/III/IV) restriction boundaries & Layer 1550 Metro Rail Influence buffers.
* **🗺️ Dual High-Definition Visuals**:
  * **Retina HD DP 2034 Map**: High-resolution zoning map complete with North Arrow ($N \uparrow$) and scale legend.
  * **Tile-Stitched Satellite Aerial View**: Pixel-aligned Esri World Imagery satellite view showing actual building structures and ground coverage.
* **🏘️ Adjoining CTS Plot Cluster Identification**: Identifies neighboring land parcels and their areas for site amalgamation and layout analysis.
* **🌍 GIS CAD & Google Earth Exports**:
  * **`.geojson`**: Scale-accurate WGS84 (`EPSG:4326`) polygon ready for AutoCAD, QGIS, and ArcGIS.
  * **`.kml`**: Interactive 3D polygon with metadata popups for Google Earth.
* **📄 2-Page Executive PDF Report Docket**: Professional PDF containing metadata tables, status banners, maps, adjoining parcel lists, and a scannable QR Code linking directly to the live MCGM Web Map.
* **📊 Centralized Excel Register**: Automatically appends query results to `output/dp-lookups.xlsx`.
* **⚡ High-Speed Concurrency & Persistent Disk Cache**:
  * Single-batch HTTP/2 async request pipelining (~800 ms fresh start).
  * Persistent disk cache store (`output/.cache_store.json`) executing repeat queries in **~12 ms**.

---

## 📋 Prerequisites

Before running `cts-dplookup-pro`, ensure your environment meets the following requirements:

### 1. System Requirements
* **Operating System**: macOS, Linux, or Windows (WSL / PowerShell)
* **Python**: Python `3.9` or higher installed

### 2. Recommended Package Manager
* [uv](https://github.com/astral-sh/uv) (Fastest Python package manager, recommended):
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

---

## 📦 Installation & Setup

### Step 1: Clone the Repository
```bash
git clone https://github.com/Eagle-imran/skillfromgemini_pro.git
cd skillfromgemini_pro
```

### Step 2: Make the Wrapper Script Executable
```bash
chmod +x cts-dplookup-pro
```

### Step 3: Install Dependencies
Using `uv` (Automatic environment & dependency resolution):
```bash
uv sync
```

*(Alternatively, using standard Python `pip`):*
```bash
pip install "httpx[http2]>=0.28.0" pillow openpyxl reportlab qrcode
```

---

## 🚀 Quick Start & Usage

Run a spatial DP lookup by providing the **Village Name** and **CTS Number**:

### Syntax:
```bash
./cts-dplookup-pro "<VILLAGE_NAME>" "<CTS_NUMBER>"
```

### Examples:
```bash
# Example 1: Query Bandra plot
./cts-dplookup-pro BANDRA 100

# Example 2: Query Worli plot
./cts-dplookup-pro WORLI 748A

# Example 3: Query Malabar Hill plot
./cts-dplookup-pro "MALABAR HILL" "16/738"
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
    ├── plot_<ward>_<cts_no>_<village>.geojson  # AutoCAD / QGIS Spatial Polygon File
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
    "autocad_geojson": "./output/<village_name>_cts_<cts_no>/plot_<cts>.geojson",
    "google_earth_kml": "./output/<village_name>_cts_<cts_no>/plot_<cts>.kml",
    "master_excel_register": "./output/dp-lookups.xlsx"
  },
  "metadata": {
    "source": "MCGM SDP 2014-34",
    "lookup_datetime": "2026-07-27 12:00:00",
    "execution_time_ms": 12.0,
    "cached_result": true,
    "interactive_web_map": "https://mcgm.maps.arcgis.com/..."
  }
}
```

---

## 🤖 Universal AI Agent Skill Integration

This repository conforms strictly to the **Agent Skill Specification (`SKILL.md`)** and can be loaded seamlessly by any AI coding assistant or autonomous agent framework:

| Agent Harness | Invocation Syntax / Mode |
| :--- | :--- |
| **Google Antigravity CLI / IDE** | `/cts-dplookup-pro <VILLAGE_NAME> <CTS_NUMBER>` or CLI execution |
| **Claude Code (Anthropic CLI)** | Executable tool invocation via shell command |
| **Cursor / Windsurf / Roo Code** | Terminal execution or agent tool call |
| **LangChain / LlamaIndex / Custom AI Agents** | Import `from cts_dp_lookup_pro import lookup_plot_pro` |

---

## 📄 License & Data Attribution

* **Data Source**: Official Municipal Corporation of Greater Mumbai (MCGM) Development Plan 2034 ArcGIS REST Services (`agsmaps.mcgm.gov.in`).
* **Satellite Base Map**: Esri World Imagery (`services.arcgisonline.com`).
* **License**: MIT License. Open-source for developers, urban planners, and real estate professionals.
