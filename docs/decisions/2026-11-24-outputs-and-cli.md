# Report, drawing and CLI behaviour

**Date:** 2026-11-24
**Status:** Accepted
**Affects:** `dp_lookup/exporters/`, `dp_lookup/exporters/templates/dossier.js`,
`dp_lookup/experimental/assemblies/service.py`, `dp_lookup/cli.py`,
`dp_lookup/database_cli.py`, `tools/audit_dxf.py`, `tests/test_dp_lookup.py`

Moved from code comments; see [2026-11-24 no code comments](2026-11-24-no-code-comments.md).

## HTML map dossier

MCGM attribute values are untrusted. Leaflet popups render HTML, so every
interpolated value passes through `esc()` (or `num()` for numbers) before it
reaches `innerHTML`.

## PDF docket

The summary table lists at most three reservations and three designations so
the docket always stays at two pages.

## DXF drawing

- The road label and the north arrow are placed before neighbouring-plot
  labels, so they claim their space first.
- The drawing keeps the full sheet available at Zoom Extents but opens on the
  selected parcel.
- Road gaps of 0.5 m or less are source alignment noise and are not reported
  as a "nearby" road.
- Text collisions can only be found by measuring rendered glyph widths. WORLI
  733 and AMBIVALI 807 passed every geometry check while carrying 16 sheet
  faults each (legend rows outside their panel, the UTM tie-in across a
  dimension, stacked grid labels).
- `tools/audit_dxf.py` treats oversized annotation on a small plot as a
  proportion warning: a 7.6 m frontage cannot hold a legible road name, which
  is harmless while the label sits outside the boundary. Only ratios above 3×
  fail.
- If PLOT DATA names an abutting road, the road layer must contain geometry.
  The audit once reported 27/27 clean while AMBIVALI 807 had no road drawn;
  absence is invisible to collision and containment checks, so it is asserted
  directly.

## Experimental assemblies

Removed internal boundary length is not inferred from perimeter reduction.
That shortcut only holds for clean edge-adjacent polygons and would treat an
overlap as a removed internal edge. The relation classifier's measured shared
edges are used instead.

## CLI

- `dp-lookup-pro lookup <village> <cts>` is the explicit form for scripts and
  future subcommands; the historical positional form stays supported.
- `db` subcommands turn any adapter exception into a stable CLI failure
  (JSON error object with `--json`).
