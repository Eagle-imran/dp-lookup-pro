# Experimental plot assemblies

Plot assemblies are an opt-in feasibility aid for studying two or more
neighbouring CTS parcels together. They are an extension of the lookup system,
not part of the normal single-plot lookup and not a legal amalgamation
approval.

## Try it

```text
dp-lookup-pro experimental assembly analyze \
  "WORLI:733" "WORLI:734" \
  --database data/mcgm-layer13.sqlite \
  --output output/experimental-assemblies/worli-733-734
```

For an explicit tolerance and machine-readable response:

```text
dp-lookup-pro experimental assembly analyze \
  "VILLAGE:CTS" "VILLAGE:CTS" \
  --database data/mcgm-layer13.sqlite \
  --gap-tolerance 0.25 --json
```

The `VILLAGE:CTS` values identify source records; they do not assert
ownership or a legally valid amalgamation.

## Scope of the experiment

The deterministic adapter reports, where the source geometry permits it:

- selected CTS identities, source ObjectIDs, snapshot and geometry checksums;
- whether inputs touch, are separated by a small gap, overlap, or are
  otherwise non-contiguous;
- the proposed geometric union and its external boundary;
- recorded area per source plot, plus polygon-calculated aggregate area for
  the selected inputs and proposed union;
- gaps, overlaps, duplicate parts, invalid geometry and other quality flags.
- combined-site zoning, reservation, designation, modification, CRZ and Metro
  intersections from the active local planning snapshot; and
- an experimental JSON analysis plus combined GeoJSON, KML and DXF hand-off
  files when the analysis completes.

Each input remains a separate source member. Raw snapshots are never rewritten
and the union is never presented as a new CTS record.

The planning result is recalculated over the exact geometric union; it is not a
sum of the member reports. The output folder contains
`assembly-analysis.json`, `assembly-boundary.geojson`,
`assembly-boundary.kml` and `assembly-boundary.dxf`. GeoJSON retains the union,
planning summary properties and every selected source plot; it does not claim
to contain planning-layer geometries. PDF, HTML, rendered DP and satellite
maps, Excel registration, road/access conclusions and automated legal-document
reconciliation are not included. Existing single-plot outputs are unchanged.

## Deterministic and non-deterministic parts

No AI, LLM or agent is required. With the same database snapshot, selected
records, software version and tolerance, selection, checksums, adjacency,
gap/overlap checks, union, areas and quality flags are deterministic.

The real-world evidence is not deterministic: MCGM data can change between
snapshots, certified surveys can disagree with cadastral geometry, and an
authority can reject or condition an amalgamation. Retain the pinned snapshot
and report with the study.

## Authority and workflow limits

MCGM cadastral geometry supports screening and site planning; it is not a
certified boundary survey. The tool cannot establish title, common ownership,
tenure, access rights, encumbrances, mutation history, or approval. It cannot
replace a Property Card, certified CTS/Final Plot plan, City Survey measurement
record, official DP Remarks plan or licensed total-station survey.

Before relying on an assembly for a proposal, reconcile every member against
certified documents and a licensed survey. A geometrically contiguous union
may still be legally or administratively impossible.

## Promotion gates

The extension remains experimental until it has:

1. offline tests for identity, multipart geometry, touching boundaries,
   tolerance, gaps, overlaps, invalid inputs and fail-closed behaviour;
2. broader parity checks against active local and selected live ArcGIS records,
   with source fingerprints retained;
3. broader reviewed planning-layer acceptance for combined geometries;
4. visual acceptance of the provenance-preserving DXF, GeoJSON and KML exports;
5. a reviewed CLI and authority/reliability contract; and
6. acceptance on real neighbouring CTS cases.

Until then it does not alter the normal lookup path, local database lifecycle,
ArcGIS ingestion or seven-artifact single-plot bundle.
