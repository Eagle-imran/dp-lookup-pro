# 📋 CHANGELOG — `dp-lookup-pro`

All notable changes to this project. Newest first.

> **If something breaks after an update, see [ROLLBACK.md](ROLLBACK.md).**

---

## [3.9.0] — 2026-07-28

Makes the tool usable without an AI assistant, and turns the commonest failure
into a self-correcting one.

### 📖 Readable output by default

The CLI printed 60 lines of raw JSON, which meant a non-technical user needed an
AI just to interpret the result. It now prints a summary:

```
  🟢 CLEAR (No Reservation)
  WORLI  ·  CTS 733  ·  Ward G/S

    Plot area         1,317.74 m²
    Zone              R
    CRZ               YES (CRZ II)
    Abutting road     Exisiting Road (N/A)
    Adjoining plots   3

    Files            ./output/worli_cts_733  (6 files)
    Fetched in 7.1s
```

An incomplete result says so in plain words and lists what is missing. A derived
area is marked as such. `--json` still prints the full response — now clean on
stdout, with progress and cache notices moved to stderr so `--json | jq` works.

**An LLM is now genuinely optional**, not a workaround for unreadable output.

### 🗺️ Village name help

`BANDRA` is not a valid village and never was — it is `BANDRA-A`…`BANDRA-I` plus
`BANDRA-EAST`. Same trap with `KURLA` and `BHANDUP`. This was the single most
likely thing to make a new user think the tool was broken.

- **`--list-villages`** prints all 128 valid names.
- A wrong name now suggests the right one:

```
'BANDRA' is not a valid MCGM village name.
Did you mean: BANDRA-A, BANDRA-B, BANDRA-C, BANDRA-D, BANDRA-E, BANDRA-EAST...?
```

- A *valid* village with a bad plot number gets a different message, so you know
  which half was wrong: *"Village 'WORLI' is valid, but it has no plot numbered
  '999999'. Suffixes and slashes matter."*

The list is held locally, so name help costs no network call.

68 tests, up from 57.

---

## [3.8.1] — 2026-07-28

Second review pass over the satellite-to-DXF pipeline. One layout defect found
and fixed; everything else measured and confirmed correct.

### 🔴 Sheet border was sized from the plot, not the drawing

The border, legend and title block were positioned from the plot outline alone.
Roads and adjoining parcels routinely extend well past the plot, so on WORLI 733
the drawing ran to x −139.8 while the border stopped at −51.8 — geometry fell
outside the frame and **the legend sat on top of it**. The sheet is now sized
from everything actually drawn, and grows downward when the legend stack is
taller than the drawing.

### ✅ Measured and confirmed correct

- **Satellite overlay alignment** — the plot outline is drawn 0.26 m E–W and
  0.14 m N–S from its true position at 0.565 m/pixel. Sub-pixel; the drawn
  outline is exactly the expected size in pixels.
- **DXF dimensions are true metres** — every boundary segment checked against
  Vincenty distances on the WGS84 ellipsoid. Worst error **4.6 cm on a 50 m
  segment** (0.09%). All 14 printed dimension labels match real geometry.
- **Setbacks** exact at 3.00 m / 6.00 m on every regenerated plot.
- **North arrow** verified to point to +Y (true north).
- **Text legibility** — smallest text is 1/190 of plot width.
- **No multi-ring plots** encountered in 14 samples. Noted as a known limit:
  `export_dxf` treats every ring as an outer boundary, so a plot with a hole
  would have that ring's setback offset the wrong way.
- `ezdxf.recover` reports **0 errors** on all files.

> Files generated before this release are stale — they carry the old radial
> setbacks and no north-arrow layer. Re-run any plot you intend to use.

---

## [3.8.0] — 2026-07-28

DXF reworked so an architect can open it and start massing immediately.

### 🔴 Setback lines were wrong

The "3 m" and "6 m" setbacks were produced by pulling each boundary vertex
*toward the plot centre*, not by offsetting perpendicular to each edge. Measured
on WORLI 733, the 3 m line sat between **1.15 m and 3.00 m** from the boundary
and the 6 m line between **2.35 m and 6.00 m**.

**Massing built to those lines would have breached the DCR.**

Now a true parallel offset. Verified on WORLI 733: 3.0000 m and 6.0000 m.
Where a plot is too small to sustain a setback it is **omitted and labelled**
rather than drawn wrong — BANDRA-A 409 (115 m²) correctly gets no 6 m line.

### 🔴 Adjoining plots were drawn 850,000 km away

Neighbour geometry arrives in Web Mercator but was treated as WGS84 degrees, so
adjoining parcels landed at ~8×10¹¹ — far outside the sheet, in **every DXF ever
generated**. Now converted correctly; they sit within metres of the plot.

### 🔴 The road layer was empty

`C-ROAD-ALIGN` was declared but never populated, so there was no way to tell
which edge was the frontage — the thing that governs the front setback. Road
geometry is now fetched and drawn. Two causes had to be fixed: geometry was not
being requested at all, and the road layers return mixed types (193/194 give
`paths`, 44/45 give `rings`) where only `paths` was read. Roads are clipped to
the plot vicinity — one came back 3.8 km long with 2,472 vertices.

### 📐 New: layer legend and plot data panel

Every DXF now carries a legend keyed to the layers, drawn on its own layers so
each swatch shows that layer's real colour and linetype:

| Layer | Meaning |
| :--- | :--- |
| `C-PLOT-BDY` | Plot boundary — gross plot area |
| `C-PROP-HATCH` | Gross plot area (fill) |
| `C-ROAD-ALIGN` | Abutting road alignment / frontage |
| `C-SETBACK-3M` | 3.0 m setback (true parallel offset) |
| `C-SETBACK-6M` | 6.0 m setback (true parallel offset) |
| `C-RESTRICT-ZONE` | CRZ / Metro development restriction |
| `C-ADJN-PLOTS` | Adjoining CTS plots |
| `C-ANNO-DIMS` | Boundary segment dimensions (m) |
| `C-ANNO-TEXT` | Plot metadata |
| `C-NORTH-ARROW` | True north |
| `0_GRID_AXIS` | Metric grid, 0,0 at plot centroid |
| `C-TITLE-BLOCK` | Sheet border, legend, title block |

Alongside it, a **PLOT DATA** panel: gross plot area and whether it is the
MCGM-approved figure or derived from the boundary, CTS/village, ward/zone,
abutting road and width, CRZ status, metro buffer, and whether each setback was
drawn or omitted.

Also added: a **north arrow** (`C-NORTH-ARROW`), CRZ restriction notes on
`C-RESTRICT-ZONE`, and a viewport that frames the whole sheet including the
legend.

### ✅ Verified

- Setbacks measured exact on square, concave-L and three live plots
- Scale confirmed: DXF polygon area matches MCGM to 0.3% on MALABAR HILL 518
- No declared-but-empty layers on any plot
- `ezdxf.recover` reports **0 errors, 0 autofixes** across all generated files
- 57 offline tests (up from 47)

> ⚠️ Setback lines are indicative geometry, not a DCPR compliance check. Actual
> requirements vary with building height, plot size and road width — confirm
> against DCPR 2034 Table 18.

---

## [3.7.0] — 2026-07-28

The first release to correct results rather than add features. Two lookups were
returning confidently wrong answers, and three separate paths could fail silently
while still producing an authoritative-looking PDF.

### 🔴 Corrected wrong results

**CRZ status was `NO` on every plot in Mumbai.**
The layer list held only *boundary lines* — High Tide Line, Low Tide Line, CRZ
Lines & Boundaries, Hazard Line. A point check at a plot's centre can never
touch a line, so the answer could only ever be `NO`. Replaced with the CRZ
*zone polygons* (layers 14, 1264, 1548). The sub-tier is now reported too, so
you get `YES (CRZ II)` rather than a bare `YES`.

| Plot | Before | After |
| :--- | :--- | :--- |
| WORLI 947 | NO | **YES (CRZ II)** |
| WORLI 886 | NO | **YES (CRZ II)** |
| BANDRA-A 409 | NO | **YES (CRZ II)** |
| BYCULLA 1605 | NO | NO ✓ *(correctly unchanged — inland)* |
| TARDEO 264 | NO | NO ✓ *(correctly unchanged — inland)* |
| **WORLI 733** | NO | **YES (CRZ II)** ✅ *(owner-verified against the actual plot)* |

⚠️ **Any PDF generated before this release understates CRZ status for coastal
plots.** Re-run anything you have issued to a client.

**Abutting roads were being missed.**
Two of the road lookups had never worked: they asked the server for roads
inside a shape, but those layers reject shape-based questions and reply with an
error that the tool read as "no roads found". Removed, and the remaining probes
now also sample along the plot's boundary edges, where roads actually run.

| Plot | Before | After |
| :--- | :--- | :--- |
| MOHILI 732 | `None` | **Road, 21.35 m** |
| WORLI 947 | B G KHER 18.30 M | unchanged ✓ |
| BYCULLA 1605 | DR ANANDRAO L NAIR RD 45.72 M | unchanged ✓ |

**Blank plot areas are now filled in.**
MCGM has no approved area on record for some parcels. The digitised boundary's
own area is used instead and clearly labelled — never presented as official.

| Plot | Before | After |
| :--- | :--- | :--- |
| MALABAR HILL 518 | *(blank)* | **2,450.16 m²** *(derived)* |
| TARDEO 264 | *(blank)* | **2,539.25 m²** *(derived)* |

New field `plot_identity.area_source` says which you got. The PDF prints
*"DERIVED from plot boundary — no approved area on MCGM record"*.

### 🛡️ Failures are no longer silent

Previously a network timeout produced `zone: Unknown`, `CRZ: NO`, no roads and
no neighbours — **and still wrote a full PDF, still logged to Excel, and cached
that result permanently.** The bad report was indistinguishable from a good one.

- A failed planning lookup now **stops the run** with a clear error instead of
  guessing.
- Partial failures appear in `metadata.warnings`, with `metadata.complete`
  saying whether the run was clean.
- **Incomplete results are never cached.**
- Server errors that arrive disguised as success (HTTP 200 carrying an error
  body) are now detected — this was the root cause of all three silent paths.
- Request timeout raised 10 s → 20 s; the old limit was routinely exceeded.

### 💾 Caching

- Expiry **24 hours → 30 days**, matched to how slowly this data actually moves
  (plot boundaries have not been edited since 2019-01-23).
- Cache hits **verify the files still exist**. Previously, deleting an output
  folder produced a confident success pointing at seven missing files.
- Every hit reports its age: `cached_at`, `cache_age_days`,
  `cache_expires_in_days`, plus a line on screen.
- Store moved to `<output_dir>/.cache_store.json` — it used to ignore your
  chosen output folder and always write to `./output`.
- **`--no-cache`** forces a fresh check.

### 🔐 Safety and correctness

- Village and CTS inputs are validated before being sent to the server, closing
  a query-injection hole.
- `&` and `<` in any name no longer corrupt the KML or crash PDF generation.

### 📦 Packaging and install

- `pip install -e .` now works, providing a `dp-lookup-pro` command that runs
  from any folder.
- Fixed a startup line that worked only on macOS — the tool previously could not
  run on Linux and could not run on Windows at all.
- Pillow minimum raised to 10.1.0; the map legend needs it.

### 🧪 Tests

47 offline tests added (`uv run pytest -q`) covering projection maths, tile
arithmetic, input validation, escaping, cache expiry, file verification and all
three vector exporters. There were none before.

### 📚 Documentation

- **`START-HERE.md`** — plain-English guide for non-technical users, including
  all 128 valid village names.
- **`APP_FLOW.html` / `APP_FLOW.json`** — system flow map, visual and
  machine-readable.
- **`LICENSE`** — proprietary, all rights reserved. The docs previously claimed
  MIT, which would have given the software away.
- Corrected every documented example: `BANDRA 100` does not exist, and `BANDRA`
  is not a valid village name at all.
- Corrected latency claims: measured **5–13 s** cold, not the ~800 ms claimed.

### ⏱️ Performance note

A single request — the DP map image — accounts for **~95% of a cold lookup**
(12.3 s of 13.0 s measured). Everything else finishes in under half a second.
The same plot re-ran at 5.2 s, so that endpoint is highly variable. This is
MCGM-side, not something the tool controls.

Cost per lookup: **₹0** — no paid APIs or keys. 25 requests, 228 KB down,
3.59 MB written to disk.

---

## [3.6.0] — 2026-07-28 (earlier)

- Native AutoCAD `.dxf` export with 11 pre-styled CAD layers.
- Query-specific bundle folders (`output/<village>_cts_<cts>/`).

## [3.5.0] and earlier

- Satellite view rebuilt on XYZ tile stitching after the previous export
  endpoint began returning HTTP 500.
- Single-batch concurrent request pipelining.
- 2-page PDF docket, HD DP map, GeoJSON and KML exports, Excel register.
