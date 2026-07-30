# 📋 CHANGELOG — `dp-lookup-pro`

All notable changes to this project. Newest first.

> **If something breaks after an update, see [ROLLBACK.md](ROLLBACK.md).**

## [3.12.0] — 2026-07-30

The DXF was opened in AutoCAD for the first time. Every geometry check had been
passing; the drawing carried **16 faults per sheet** anyway.

### 🔴 Why none of this was caught before

Whether a label overruns a frame or lands on another label depends on the
**rendered width of a glyph**, not on where its insertion point sits. Nothing in
the codebase had ever measured text. Two root causes:

* The legend panel height was `lg_row * (n_legend + 9.5)` — a magic constant that
  **never counted the PLOT DATA rows at all**. Three rows fell outside the panel
  border on every drawing ever generated. A second copy of the row count
  (`_legend_rows_n = 12`) lived in a different function and could drift freely.
* The sheet-border extent scan read `LWPOLYLINE`, `LINE` and `CIRCLE` — **never
  `TEXT`**. Labels were invisible to the code sizing the border meant to contain
  them.

### ✅ Added — text measurement

`text_extents()` measures a `TEXT` entity through ezdxf's font engine, applying
rotation to the corners so rotated dimensions measure correctly.
`boxes_overlap()` and `nudge_text_clear()` build on it. Panel frames are now
drawn **last** and sized from their measured contents; `legend_column_height()`
derives the height from the row lists themselves.

`tools/audit_dxf.py` runs the whole check and exits non-zero on any fault.

### 🔴 Fixed

| Fault | Detail |
| :--- | :--- |
| Panel border cut across PLOT DATA | 3 rows outside the frame, worst 10.21 m below |
| Legend rows overran the panel | 4 rows on WORLI 733; **19.83 m** on AMBIVALI 807 |
| A row escaped the sheet border | +0.35 m (WORLI), **+16.66 m** (AMBIVALI) |
| UTM tie-in lay across dimensions | removed — it was already in the title block verbatim, and was the widest annotation on every sheet |
| Two grid labels stacked at the corner | X-row and Y-column both labelled the origin corner |
| Neighbour label on a dimension | `CTS 733A` over `10.23m` |
| Two dimensions on each other | `6.20m` over `3.47m` on short adjacent edges |
| CRZ note over a neighbour label | notes now clear everything already placed |
| Opaque plot fill | hid survey underlays and satellite images; now 65% transparent |
| No plot hierarchy | all 12 layers were on default lineweight, so the grid plotted as heavy as the boundary |
| Legend overpromised a CRZ polygon | `C-RESTRICT-ZONE` carries advisory text only — CRZ comes from a point identify, not a polygon |

### 🔴 Metro buffer restriction was never drawn — on any plot, ever

Found while checking why `C-RESTRICT-ZONE` held only its legend swatch on
AMBIVALI 807, a plot that **is** in a Metro Buffer Zone.

The lookup sets the flag to `"YES (Metro Buffer Zone)"`. `export_dxf` tested
`== "YES"`. That comparison has never once been true, so the metro influence
circle and its note were silently absent from every DXF this tool has produced.

This is the same failure mode as the CRZ false negative fixed in 3.7 — an exact
string match where the data carries a qualifier. The CRZ check already used
`.upper().startswith("YES")`; both now share that shape.

It survived the empty-layer test because the legend draws a sample line *on*
`C-RESTRICT-ZONE`, so the layer counted as populated on the strength of its own
swatch. There is now a test that requires real geometry, not a swatch.

### 🔴 Roads were dropped when their vertices were far apart

`C-ROAD-ALIGN` was empty on AMBIVALI 807 even though MCGM had returned the
frontage name and a 27.4 m width. The clip that trims MCGM's kilometre-long road
networks to the plot vicinity kept a road only when one of its **vertices** landed
inside the window. MCGM centrelines can run a kilometre between vertices, so a
road passing directly along the plot's edge was discarded entirely.

Demonstrated with the same road at two vertex densities:

| Road geometry | Drawn before | Drawn now |
| :--- | :--- | :--- |
| Vertices ~100 m apart | ✅ | ✅ |
| Vertices ~1.1 km apart, same alignment | ❌ | ✅ |
| Genuinely misses the plot | ❌ | ❌ |

Now clipped with Liang-Barsky on each **segment**, so a segment that crosses the
window is kept and trimmed to it. Trimming matters as much as keeping: retaining a
whole 1.1 km segment would have dragged the sheet border out with it.

This one matters for the deliverable — the frontage is what governs the front
setback, and an architect had no way to tell which edge faced the road.

### 🟠 Two areas are now printed, and the gap is named

MCGM's approved record, MCGM's **own** digitised polygon, and the Property Card
are three independent sources that do not agree:

| Plot | MCGM record | Drawn boundary | Gap |
| :--- | ---: | ---: | ---: |
| WORLI 733 | 1317.74 m² | 1321.74 m² | +0.30% |
| AMBIVALI 807 | 2019.00 m² | **2142.25 m²** | **+6.10%** (123 m²) |

The sheet printed one figure and labelled it `MCGM approved record`, so an
architect measuring the polyline got a number that appeared nowhere on the
drawing. PLOT DATA now carries `MEASURED (BDY)` with the percentage delta, and the
title block states that the Property Card may differ and must be reconciled
before any FSI calculation. The owner measured 5–7% against the Property Card on
WORLI 733.

### 🔴 The first fix pass only worked on the two plots it was tested against

Regenerating all 27 bundles and auditing every one gave **17 clean, 10 with
faults**. WORLI 733 and AMBIVALI 807 were clean; that did not generalise. Three
further causes, found only by running the audit across the whole set:

* **`text_extents` was wrong for aligned text** — a bug in the measuring helper
  itself. It read `dxf.insert` unconditionally, but aligned text stores its anchor
  in `align_point` and grows *around* it. The centred `CTS <n>` label therefore
  measured half a width right and half a height high, so every collision verdict
  involving it was unreliable. Now honours `halign`/`valign`, composed correctly
  with rotation.
* **Near-collinear slivers could not be separated by nudging.** Pushing a label out
  along its edge normal separates neighbours when the edges turn, but on a run of
  slivers the normals are nearly parallel, so labels travelled together and never
  cleared — DADAR-NAIGAON 98 had **seven** mutual collisions among labels of
  1.07–1.34 m. Now the longest edges are labelled first, so the dimensions an
  architect needs win their position, and a label that still cannot be placed clear
  is removed rather than left overlapping. Across all 27 plots this drops
  **1 label out of 388 (0.3%)**.
* **The centre label was placed last**, so nothing ever checked against it and a
  boundary dimension could land on it (`12.00m` over `CTS 1862`). It is now placed
  before the annotation that has to avoid it. Same for the setback-N/A markers,
  which collided with the road label below the plot on BANDRA-A 409.

In-drawing labels are now budgeted against the plot they annotate
(`fit_label_to_width`) rather than a fixed character count.

The audit's annotation-width check was also too strict to be useful — it failed at
1.01× plot width. On a 7.6 m plot any legible text is wide relative to the plot;
that is inherent and harmless while the label sits outside the boundary, which the
collision and border checks already enforce. It now warns above 1.5× and fails only
above 3×.

**All 27 bundles audit clean.**

### 🟢 Small plots

Long strings were shortened to markers where the panel already carries the full
wording — the setback-not-viable notice ran **3.8×** the width of an 8 m plot, and
the CRZ notice 3.3×. Long road names wrap in the panel instead of widening it
(AMBIVALI 807's frontage is 56 characters).

### 🧪 Tests: 115 → 130

Covers text measurement and rotation, the nudge loop including its failure case,
the legend height regression, road-name wrapping, dual-area disclosure, and
generated-drawing assertions for border containment, panel containment, zero
collisions, unique grid labels, lineweights, fill transparency, and annotation
scale on an 8 × 16 m plot.

**Verified:** WORLI 733 and AMBIVALI 807 both go 16 faults → 0.

---

## [3.11.0] — 2026-07-30

### 📁 Repository Folder Structure & Documentation Hierarchy Cleanup

Reorganized project layout to declutter the root directory and streamline navigation for developers and AI agents.

* **Root Directory Minimization**: Kept root clean with only core entry files (`README.md`, `START-HERE.md`, `SKILL.md`, `LICENSE`, `pyproject.toml`, `cts_dp_lookup_pro.py`).
* **Documentation Hierarchy (`docs/`)**: Moved all technical reference specs, architectural guides, version logs, and flow maps into `docs/` (`DXF-GUIDE.md`, `CHANGELOG.md`, `FEATURES_PLANNED.md`, `ROLLBACK.md`, `MEMORY.md`, `APP_FLOW.html`, `APP_FLOW.json`).
* **Agent Guidance**: Updated `docs/MEMORY.md` with explicit repository layout rules and documentation policies for future AI coding agents.

---

## [3.10.1] — 2026-07-29

Rendered the DXF and looked at it. Found a defect no geometry check could catch.

### 🔴 Plot metadata was printed across the plot

`C-ANNO-TEXT` drew an eight-line block — CTS, village, ward, area, zone, status,
road, UTM — starting near the plot centroid. On screen it covered the boundary
and **both setback lines**: exactly the area an architect needs clear to draw in.

Every geometry check passed, because nothing was geometrically wrong. It was
only visible once rendered.

The block is also redundant — the legend's PLOT DATA panel already carries all
of it. The centroid now shows just `CTS <number>`, with the UTM tie-in moved
above the plot.

### Also fixed by looking

- CRZ notes, the UTM line and the road label were stacked at 1.4× line spacing
  and overlapped each other and the top boundary edge. Now 2.1×.
- Sub-metre boundary segments produced a cluster of unreadable overlapping
  dimension labels. Labels are now omitted below 1.0 m; the segment is still
  drawn, and sub-metre slivers are digitisation noise rather than real frontage.

### 🔍 New: `tools/render_dxf.py`

```bash
uv run python tools/render_dxf.py output/worli_cts_733/plot_G-S_733_worli.dxf --zoom
```

Renders a DXF to PNG via ezdxf's matplotlib backend. Not a substitute for
AutoCAD, but it catches what measurement cannot: overlapping text, annotations
sitting on geometry, a legend covering the drawing, layers that render
invisible. Requires the dev extra (`uv pip install -e ".[dev]"`).

### Known cosmetic limit

On small plots (Bandra-A 409 is 7.6 × 16.4 m) annotation text is wide relative
to the plot, because text height is floored at a 30 m reference scale. The notes
sit outside the boundary so nothing is obscured, and annotation layers can be
switched off — but it looks cramped. Worth a look when the drawing is opened in
real CAD.

---

## [3.10.0] — 2026-07-29

The planning answer no longer waits for the pictures.

### ⚡ Answer in ~0.7s instead of ~6.5s

A lookup fires 25 requests. The planning data — zone, reservation, CRZ, metro,
road, neighbours — is ready long before the DP map image, which is consistently
the slowest single request (5.6–5.9s measured). Previously the whole answer
waited on it.

The wait is now split. Vector exports (GeoJSON, DXF, KML) need geometry only, so
they are written in the fast half too. The CLI prints the result as soon as it is
known, then finishes the map, satellite view and PDF:

```
    CRZ               YES (CRZ II)
    ...
    Fetched in 0.7s

  Building PDF, maps and CAD files...
  Done in 6.5s - all 6 files written.
```

Measured on WORLI 733, three consecutive runs:

| Run | Answer visible | All files | Perceived |
| :--- | ---: | ---: | ---: |
| 1 | 4,746 ms | 6,246 ms | 1.3× |
| 2 | 700 ms | 6,470 ms | **9.2×** |
| 3 | 635 ms | 6,443 ms | **10.1×** |

**Typically ~10×.** Run 1 shows the honest caveat: one identify request stalled
at 4,470 ms, and the fast half can only be as quick as its slowest call. MCGM is
slow *and variable* across every endpoint, not just the map export — an earlier
note in this changelog attributed 95% of runtime to `/export` alone, which held
for that measurement but is not reliably true.

Nothing is skipped or deferred to a detached task: the same six files are written
before the process exits, and the final returned result is unchanged.

### API

`lookup_plot_pro(..., on_data=callback)` — called with the planning result as
soon as it is known, carrying `metadata.documents_pending: True`. The returned
dict is the final one. A callback that raises is caught and logged, never allowed
to abort the lookup. Omit it and behaviour is exactly as before.

70 tests, up from 68.

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
