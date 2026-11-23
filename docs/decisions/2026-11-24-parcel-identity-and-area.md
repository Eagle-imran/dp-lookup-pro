# Parcel identity, split parcels and plot area

**Date:** 2026-11-24
**Status:** Accepted
**Affects:** `dp_lookup/application/ingestion.py`, `dp_lookup/clients/local_parcels.py`,
`dp_lookup/core/topology.py`, `dp_lookup/application/neighbour_normalization.py`,
`dp_lookup/application/local_spatial.py`, `dp_lookup/application/planning_normalization.py`,
`dp_lookup/core/constants.py`, `tools/audit_dxf.py`

These decisions were previously recorded as inline code comments. They were
moved here when code comments were banned (see
[2026-11-24 no code comments](2026-11-24-no-code-comments.md)).

## Split parcels are one plot

MCGM Layer 13 can store one village/CTS identity as several source features.
Live and local lookups both combine every part (`_merge_live_matches`,
`local_parcels`). Using only the first part understates the boundary and
every planning overlap computed against it.

- Overlapping or edge-sharing source parts become a derived union
  (`core/topology.py`), never an invalid MultiPolygon whose area double-counts
  the overlap.
- **Recorded area:** a single value repeated across parts can stay the stated
  area. When parts disagree, the parts are neither summed nor resolved to the
  first record. The recorded area becomes unavailable, the calculated combined
  boundary area is used, and the result says the area was derived.

## Never report another plot under the requested number

The live `LIKE 'n%'` retry accepts only plots whose stored CTS number equals
the request after trimming and case-folding. Anything else stops the lookup
and lists the similarly numbered plots.

## Adjoining parcels

Only a shared boundary edge makes parcels adjoining. A point-only (corner)
contact or an overlap is a data-quality relationship, not adjacency.

## Local versus live boundaries in `auto` mode

In `auto` mode the parcel adapter can legitimately fall back to live ArcGIS.
Local spatial helpers then return `None` instead of an empty local result, so
the established live boundary query runs rather than falsely reporting "no
neighbours".

## Polygon checks outrank point identify

A successful polygon query that returns nothing means "no qualifying
overlap". A point identify can hit an adjacent feature, so it never replaces
a successful polygon result for layers 46, 47 and 192.

## Plot-area discrepancies must be disclosed

A gap between MCGM's recorded area and MCGM's own digitised polygon is real
data, not a bug (AMBIVALI 807 differs by 6.10%). The DXF audit fails a sheet
that does not disclose a gap above 2%, so nobody computes FSI from an
unreconciled figure. Silence is the fault, not the discrepancy.

## Source data quirks

- MCGM records an unnamed carriageway under several placeholder names,
  including the misspelling `exisiting road`. `GENERIC_ROAD_NAMES` keeps them
  all.
- The 128 valid revenue village names in `MCGM_VILLAGES` were read from Layer
  13 on 2026-07-28.
