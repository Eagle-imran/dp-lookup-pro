# 📐 Reading the DXF — a note for the architect

You've been sent a `.dxf` for a Mumbai plot, generated from the MCGM
Development Plan 2034. This explains what's in it, what you can build on, and
what you still need to check yourself.

---

## Opening it

Double-click. It opens in AutoCAD, AutoCAD LT, Civil 3D, BricsCAD, TurboCAD or
anything that reads DXF R2010.

- **Units are metres.** 1 drawing unit = 1 metre. No scaling needed.
- **Origin (0,0) is the plot's centre.** Everything is positioned around it.
- **Up is true north.** There's a north arrow on `C-NORTH-ARROW`.
- **Nothing is a block or an xref.** Plain geometry on named layers — delete,
  trace over or copy into your own file freely.

---

## What's on each layer

There's a **legend printed in the drawing itself**, to the right of the plot,
plus a **PLOT DATA** panel with the numbers. Here's the same thing in words:

| Layer | What it is | Use it for |
| :--- | :--- | :--- |
| **`C-PLOT-BDY`** | The plot boundary — your **gross plot area** | The site outline. Everything starts here. |
| `C-PROP-HATCH` | Shading inside the boundary, 65% transparent | Visual only. Transparent so you can put a survey or satellite underlay beneath it. |
| **`C-ROAD-ALIGN`** | The **abutting road**, with its name and width | Identifies your **frontage** — which edge faces the road. |
| **`C-SETBACK-3M`** | A line exactly **3 m inside** every boundary edge | Indicative building line. |
| **`C-SETBACK-6M`** | A line exactly **6 m inside** every boundary edge | Indicative building line for taller massing. |
| `C-RESTRICT-ZONE` | CRZ or Metro restriction **notes** — advisory text, not a zone boundary | **Read this before massing.** CRZ caps what you can build. |
| `C-ADJN-PLOTS` | Neighbouring CTS plots, with their numbers | Amalgamation studies, party walls, overlooking. |
| `C-ANNO-DIMS` | Length of each boundary segment, in metres | Checking frontage width and depth. |
| `C-ANNO-TEXT` | Just the CTS number at the centre | Reference. Full metadata is in the PLOT DATA panel. |
| `C-NORTH-ARROW` | True north | Sun path, orientation. |
| `0_GRID_AXIS` | 25 m or 50 m grid, labelled | Quick distance sense. Turn it off when drawing. |
| `C-TITLE-BLOCK` | Sheet border, legend, title block | Reference. |

Every layer carries an **explicit lineweight**, so the sheet plots with hierarchy:
the plot boundary is the heaviest line, setbacks sit below it, and the grid,
neighbours and annotation sit below that.

There is **no CRZ polygon** on `C-RESTRICT-ZONE`, only notes. CRZ status is
established by a point query at the plot centroid, so there is no zone outline to
draw — and a layer that implied one would be misleading.

**If a setback layer is empty**, the plot is too narrow to take that setback —
you'll see a `SETBACK N/A` marker on the layer, with the full wording in the PLOT
DATA panel. That's deliberate: better a missing line than a wrong one.

---

## ⚠️ The plot area: check which number you are using

Three sources give three different answers, and they are **not** interchangeable:

| Source | Where it appears |
| :--- | :--- |
| **MCGM approved record** (`AREA_APP_SQ_MTRS`) | `GROSS PLOT AREA` in the PLOT DATA panel |
| **The drawn boundary** — what AutoCAD's `AREA` command returns | `MEASURED (BDY)` in the same panel, with the percentage difference |
| **The Property Card** (City Survey Office) | Not in this drawing. This tool cannot read it. |

The gap between the first two is usually small but sometimes is not: on WORLI 733
it is 0.30%, on AMBIVALI 807 it is **6.10% — 123 m²**. Both figures are printed so
that the difference is visible rather than buried.

**Reconcile all three before computing FSI.** A 6% error on a 2000 m² plot is
120 m² of assumed plot area, which at Mumbai FSI compounds into several hundred
square metres of built area.

---

## ⚠️ What changed, and why it matters to you

If you were given one of these files **before 28 July 2026**, three things in it
were wrong. Please re-request any plot you're actively working on.

### 1. The setback lines were not at the distance they claimed

This is the serious one. The lines labelled 3 m and 6 m were drawn by pulling
each corner of the plot toward the middle, rather than by offsetting each edge
perpendicular to itself.

On a real plot we measured, the line labelled **"3 m" was as close as 1.15 m** to
the boundary, and the **"6 m" line as close as 2.35 m**.

**Massing built to those lines would have breached the setback.** They're now
true parallel offsets, measured exact at 3.000 m and 6.000 m.

### 2. Neighbouring plots weren't where they should be

Adjoining plots were placed hundreds of thousands of kilometres from the site
because of a coordinate error — so when you zoomed to fit, you saw nothing
useful. They now sit correctly, within metres of your boundary.

### 3. The road wasn't drawn at all

The road layer existed but was always empty. You had no way to tell which edge
of the plot was the frontage — and frontage determines the front setback. The
abutting road is now drawn, named and dimensioned.

---

## What you can trust, and what you must check

**Reasonably reliable:**

- **Plot shape and dimensions.** The drawn area matches MCGM's record to within
  ~0.3% on plots where both are available.
- **Orientation.** North is up.
- **Road name and width**, where MCGM has it recorded.
- **Zone, reservation and CRZ status** — these come straight from the DP 2034
  layers.

**Check before you rely on it:**

- **⚠️ The setback lines are indicative geometry, not a compliance check.**
  They are simply "3 m in" and "6 m in". Your actual requirement depends on
  building height, plot size and road width — see **DCPR 2034 Table 18**. Treat
  them as a starting envelope, not an approval.
- **⚠️ Gross plot area.** The PLOT DATA panel says whether the area is MCGM's
  *approved* figure or one *derived from the drawn boundary*. Where both exist
  they can differ by up to 7%. For anything contractual, use the approved area
  from the Property Register Card.
- **⚠️ This is not an official DP Remark.** It's the public map data, formatted.
  Get the official remark from MCGM before committing to a scheme.
- **⚠️ FSI is not calculated.** Nothing here tells you permissible built-up
  area. That's yours to work out under DCPR 2034.

---

## A suggested way in

1. Open the file and **Zoom Extents** — you'll see the plot, the legend on the
   right, and the title block.
2. Read the **PLOT DATA** panel: gross area, zone, road and width, CRZ status.
3. Check **`C-RESTRICT-ZONE`** first. If the plot is in CRZ, that constrains
   everything downstream.
4. Identify your frontage from **`C-ROAD-ALIGN`**.
5. Confirm your real setbacks against **DCPR 2034 Table 18** for your intended
   height — then adjust or redraw the setback lines accordingly.
6. Trace your building envelope inside the corrected line.
7. Use **`C-ADJN-PLOTS`** to check overlooking, party walls, or amalgamation
   potential.

---

## If something looks wrong

The plot boundary comes from MCGM's cadastral layer and is only as good as their
digitisation. If the shape doesn't match the site survey, **trust the survey**.
This drawing is a planning base, not a measured survey.

---

*Generated by `dp-lookup-pro` v3.10.1 from MCGM Development Plan 2034 data.
Indicative only — not an official DP Remark and not certified by MCGM.*
