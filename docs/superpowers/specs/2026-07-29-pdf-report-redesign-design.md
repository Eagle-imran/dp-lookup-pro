# PDF Report Redesign — Design

**Date:** 2026-07-29
**Status:** Approved, ready for implementation planning
**Affects:** `build_pdf_doc` in `cts_dp_lookup_pro.py`

---

## Problem

The generated PDF was inspected by rendering it to images. Three faults:

1. **The status badge is broken.** It renders as `■ CLEAR (No Reservation)` — the
   🟢/🟡/🔴 emoji are not present in ReportLab's default Helvetica, so the single
   most important element on the page is an empty box. The same break appears in
   the DP map legend image.
2. **Roughly a third of each page is blank.** Page 1 ends after the map; page 2
   has ~40% empty below the adjoining-parcels table.
3. **The hierarchy is flat.** `CRZ Status: YES (CRZ II)` — a finding that
   restricts what can be built — sits in a table row visually identical to
   `Metro Buffer: NO`. Nothing directs the reader to what matters.

## Reader

**Mixed, and forwarded.** It starts with the tool's owner but reaches clients,
architects and consultants. It must work *cold*, with no one present to explain
it: headline verdict legible in seconds for a non-technical reader, full
constraint detail intact for a professional.

Two consequences that drive the design:

- Forwarded documents get **printed in black and white**. Status must never
  depend on colour alone.
- The document represents its sender, so it needs an identity slot — but the
  owner is not ready to commit to branding, so branding is **optional and
  absent by default**.

## Goals

- A reader understands the verdict and the governing constraints within seconds.
- Nothing depends on a glyph the font lacks.
- Reclaimed whitespace carries useful content, not decoration.
- The document does not read as an official MCGM remark.
- Branding can be switched on later without a redesign.

## Non-goals

- No FSI or buildable-area calculation. Out of scope, and legally risky.
- No change to the lookup engine, exports, or DXF.
- No interactive/HTML report. Separate roadmap item.

---

## Structure

### Page 1 — the decision page

| Block | Content | Purpose |
| :--- | :--- | :--- |
| Header | Optional logo + firm, title, reference, date | Identity slot; renders clean when unbranded |

**Reference format:** first three letters of the village + CTS number, uppercased
and non-alphanumerics stripped — `WORLI` + `733` → `WOR-733`. Deterministic, so
the same plot always yields the same reference. It is a human-readable label for
correspondence, **not** a unique identifier: two villages sharing a three-letter
prefix (`MALABAR HILL` and `MALAD`, both `MAL`) can collide on the same CTS
number. The village and CTS appear in full in the verdict band directly below.
| **Verdict band** | Status word + colour band; village, CTS, ward, area | The five-second answer |
| **Constraint cards** ×3 | Zone · CRZ · Frontage | The three findings that govern development |
| Detail table | Reservation, designation, DP modification, metro buffer, area source | Supporting detail, deliberately quieter |
| Map | DP 2034 zoning map, full width | Fills today's blank third |
| Footer | Indicative-only notice + QR to the live map | Prevents misuse as an official remark |

### Page 2 — the evidence page

| Block | Content |
| :--- | :--- |
| Header | Site context, plot identity |
| Satellite | Full width |
| Adjoining parcels | CTS number, village, area |
| **Files in this bundle** | What the `.dxf`, `.kml`, `.geojson` are for |
| **Method & limits** | Data source, fetch date, that setbacks are indicative, disclaimer |

The last two blocks are new and exist to fill page 2's empty 40% with content
that earns its place.

---

## Visual system

### Colour

One semantic colour per status: clear / modified / reserved. Neutrals are chosen
rather than inherited — a warm-grey text colour on a paper-white ground, so the
document does not read as default ReportLab.

**Constraint:** the verdict band carries the status **word and** the colour.
Colour is never the sole carrier of meaning, because this document will be
printed in greyscale. The same rule applies to the CRZ card.

### Typography

Embed **IBM Plex Sans** (text) and **IBM Plex Mono** (reference numbers,
coordinates).

Reasons, in order of weight:

1. **Tabular numerals.** The report is largely numbers in columns — areas, road
   widths, coordinates. Proportional figures misalign and read as careless.
2. **OFL licence**, so redistribution with the tool is clean.
3. A technical rather than corporate character, appropriate to a municipal
   document.

Approximately 350 KB for the required weights.

Inter is deliberately not used: it is the default reach and would leave the
document looking like every other generated PDF.

⚠️ **The licence file must be read and confirmed to permit redistribution before
the font ships.** Not assumed.

If font registration fails at runtime for any reason, the builder falls back to
Helvetica and still produces a valid report.

---

## Branding

Optional dict, absent by default:

```python
branding = {"firm": "…", "logo": "path/to/logo.png"}   # both optional
```

- Absent → header shows title, reference and date only, correctly spaced.
- `firm` only → firm name set alongside the title.
- `logo` present but unreadable → skipped with a warning; the report still builds.

---

## Implementation shape

`build_pdf_doc` currently takes **21 positional arguments** across ~120 lines.
Adding cards and branding to that signature would make it unmaintainable.

**Change:** accept the `result` dict the caller already holds, plus paths and
optional branding. Split rendering into small builders, each returning
ReportLab flowables:

```
_header(result, branding)      -> [Flowable]   # page 1: identity + title
_page2_header(result)          -> [Flowable]   # page 2: "SITE CONTEXT" + plot ref
_verdict_band(result)          -> [Flowable]
_constraint_cards(result)      -> [Flowable]
_detail_table(result)          -> [Flowable]
_map_block(path, caption)      -> [Flowable]
_adjoining_table(result)       -> [Flowable]
_files_block(result)           -> [Flowable]
_limits_block(result)          -> [Flowable]
_footer(result, qr_bytes)      -> [Flowable]
```

Each is independently testable and small enough to reason about. The call site
loses 21 positional arguments.

`build_pdf_doc` keeps its name and remains the single entry point, so the
existing call in `lookup_plot_pro` changes only its arguments.

---

## Error handling

| Condition | Behaviour |
| :--- | :--- |
| Font fails to register | Fall back to Helvetica; report still builds |
| Logo path missing or unreadable | Skip logo, warn to stderr, continue |
| Road name too long for a card | Truncate in the card; full name stays in the detail table |
| Area is `None` (no MCGM record) | Show the derived value with its `area_source` label |
| `&` or `<` in any field | Already escaped via `_esc`; behaviour preserved |
| Map or satellite image missing | Placeholder block with an explanatory caption, not a crash |

---

## Testing

The PDF has **no test coverage today**. Add, using pymupdf text extraction
(dev-only dependency):

- Page count is 2.
- Extracted text contains the status word, CTS number, village, and CRZ tier.
- **No `■` or replacement glyph** appears anywhere — the regression that started
  this work.
- Report builds with branding absent, with `firm` only, and with an unreadable
  logo path.
- Report builds when the font is unavailable (Helvetica fallback).
- Report builds when `area_sqm` is `None`.
- A road name containing `&` does not break the build.

---

## Risks

| Risk | Mitigation |
| :--- | :--- |
| Three cards may not fit a long road name | Truncate in card, full value in detail table; verified against `KHAN ABDUL GAFFAR KHAN MARG` |
| Font licence may forbid redistribution | Read the licence before shipping; Helvetica fallback already exists if it must be dropped |
| Font adds ~350 KB to the repo | Accepted; it is the single largest lever on how the document reads |
| Greyscale printing loses status colour | Status word always accompanies the colour |
| Refactor could regress a working PDF | Golden-file check: render before and after on a known plot and compare extracted text |

---

## Verification

Rendered visually with pymupdf before and after, on at least:

- **WORLI 733** — CLEAR, CRZ II, long road name, approved area
- **BYCULLA 1605** — MODIFIED status, named road, DP modification present
- **MALABAR HILL 518** — RESERVED/designated, derived area, null approved area

All three status colours and both area sources are exercised.
