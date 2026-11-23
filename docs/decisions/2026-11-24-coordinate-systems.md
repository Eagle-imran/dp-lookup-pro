# Coordinate systems and units

**Date:** 2026-11-24
**Status:** Accepted
**Affects:** `dp_lookup/core/area_assessment.py`, `dp_lookup/core/geometry.py`,
`dp_lookup/core/constants.py`, `dp_lookup/application/output_layout.py`

Moved from code comments; see [2026-11-24 no code comments](2026-11-24-no-code-comments.md).

## The internal pipeline is Web Mercator

Geometry flows through the pipeline in EPSG:102100/3857 (Web Mercator)
metres, the coordinate system of MCGM's map service. Web Mercator "metres"
are not ground metres in Mumbai, so:

- **Areas** are measured in WGS 84 / UTM zone 43N (EPSG:32643). Zone 43N spans
  longitudes 72°E–78°E and its central meridian is 75°E. Geometry outside
  that range (synthetic test data, non-Mumbai input) is not projected; the
  caller keeps scale 1.0 instead of producing a misleading figure far outside
  the zone.
- **Distances** measured upstream in Web Mercator units, such as the road gap
  in `output_layout.py`, are scaled by `cos(latitude)` before display.
- **Probe offsets** in `ROAD_EDGE_NUDGES` are Web Mercator units, not ground
  metres.

Tests build local snapshot fixtures in Web Mercator metres around Mumbai so a
degree-as-metre confusion produces obviously wrong latitudes.
