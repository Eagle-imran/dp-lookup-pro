# Local parcel and planning snapshot database

**Status:** Implemented; first local snapshot built, verified and activated
**Updated:** 2026-08-21
**Scope:** MCGM Development Plan 2034 Layer 13 plus the audited planning registry

## Purpose

This component gives the tool reliable local copies of parcel identity,
geometry and planning-layer evidence. It is a **snapshot database**, not a
transparent cache of a report: parcel and planning datasets keep independent
source records, validation, active pointers and lifecycle history in one
SQLite file. CLI `auto` uses both locally first and falls back visibly when a
local source cannot answer. Stale parcel data remains usable with a warning;
stale planning falls back live because planning status is more change-sensitive.

The database is deliberately not committed to Git. Generated files under
`data/*.sqlite` and their SQLite sidecars are ignored by `.gitignore`.

## Verified source facts

The completed local build and immediate live recheck (2026-08-21) measured:

| Measure | Count |
| :--- | ---: |
| Feature records in the source inventory | **135,342** |
| Records with a non-empty CTS/CS number | **123,388** |
| Records without a CTS/CS number | **11,954** |
| Duplicate village/CTS identity groups | **3,050** |
| Extra feature records in those groups beyond one each | **3,869** |
| Canonical planning layers | **52** |
| Planning-layer records | **65,604** |
| Planning validation errors | **0** |
| Planning source-geometry warnings | **3** |

These are feature-record counts, not a claim that there are 135,342 unique
legal plots. A village/CTS identity can contain multiple source features and
multipart geometry. The importer preserves those parts and the local lookup
combines all matching source features. Counts are re-measured on every build;
the figures above must not be treated as a permanent constant.

The three planning warnings are official Designation records 1158, 1159 and
4817 with empty source rings. They remain complete inventory records but cannot
produce a spatial intersection. The active combined database is about 1.0 GiB.

## What is implemented

### Ingestion

`dp_lookup.clients.parcel_snapshot` and
`dp_lookup.application.snapshot_ingestion` provide a bounded, crash-resumable import:

1. Request the complete Layer 13 ObjectID inventory.
2. Download ObjectIDs in sequential batches with retry/backoff.
3. Request all source attributes and exact polygon geometry.
4. Reconcile expected, received, missing, rejected, duplicate, and extra IDs.
5. Commit each accepted batch atomically into a `building` SQLite snapshot.
6. Preserve the canonical raw ArcGIS feature JSON, attributes and exact geometry.
7. On restart, resume only when the persisted inventory hash matches exactly,
   skipping ObjectIDs already committed to SQLite.
8. Refuse to finalize or activate an incomplete source result.

The current service uses a 2,000-feature batch and a gentle delay between
requests. It does not retain all 135k feature objects in memory. SQLite itself
is the checkpoint: an interrupted batch rolls back, earlier committed batches
remain, and rerunning the same command resumes them. It is intentionally
suitable for a periodic internal update, not an unbounded scraping job.

### SQLite store

`dp_lookup.spatial_store.SnapshotStore` uses the Python standard-library
`sqlite3` module. It stores:

- immutable lifecycle states: `building`, `ready`, `active`, `retired`, `failed`;
- source URL, expected/received counts, timestamps, manifest and validation JSON;
- canonical raw feature JSON, raw attributes, ObjectID, normalized lookup keys,
  village, CTS, ward, type, approved area and exact source rings (no
  simplification or reprojection in the store);
- the exact source ObjectID inventory used to prove set equality, rather than
  relying only on a matching record count;
- per-feature bounding boxes and an R-Tree when the local SQLite build supports
  it, with a correct indexed bounding-box fallback when it does not;
- ingestion runs, issues, activation history, duplicate identity groups, and
  snapshot-to-snapshot diffs.

A `ready` or `active` snapshot cannot be edited. A new build is inserted as a
separate `building` snapshot, validated, and only then made `ready`; activation
switches the active pointer atomically. A previous snapshot remains available
for rollback.

### Planning snapshot store

`dp_lookup.planning_snapshot.PlanningSnapshotStore` uses separate
`planning_*` tables and its own activation history in the same file. The
planning builder archives all official fields for future audit, but runtime
evidence exposes only the registry allow-list. Local core and optional evidence
adapters use the R-Tree to shortlist features and the shared live/local parser
for exact intersection, sliver removal and authority rules. See the [planning
snapshot contract](PLANNING_SNAPSHOT.md) for counts, warnings and refresh rules.

### Local lookup and exact adjacency

The CLI can use an active local snapshot through `LocalParcelFetcher` and
`LocalNeighbourProvider`. A local lookup combines every Layer 13 feature with
the requested village/CTS identity, preserving multipart plots and retaining
the source ObjectIDs.

Local adjacency uses the snapshot's spatial index to shortlist nearby features,
then Shapely to calculate shared boundaries and small digitisation gaps. The
result is marked `method: "spatial_database"` and `evidence_state: "confirmed"`.
This is exact for the coverage in the active snapshot; it is not the old four
point-probe approximation.

## CLI contract

Database administration requires an explicit file path:

```bash
dp-lookup-pro database build    --database data/mcgm-layer13.sqlite
dp-lookup-pro database status   --database data/mcgm-layer13.sqlite
dp-lookup-pro database verify   --database data/mcgm-layer13.sqlite
dp-lookup-pro database diff     --database data/mcgm-layer13.sqlite
dp-lookup-pro database activate --database data/mcgm-layer13.sqlite
dp-lookup-pro database rollback --database data/mcgm-layer13.sqlite

dp-lookup-pro database build-planning    --database data/mcgm-layer13.sqlite
dp-lookup-pro database status-planning   --database data/mcgm-layer13.sqlite
dp-lookup-pro database verify-planning   --database data/mcgm-layer13.sqlite
dp-lookup-pro database activate-planning --database data/mcgm-layer13.sqlite
dp-lookup-pro database rollback-planning --database data/mcgm-layer13.sqlite
```

Each build downloads and validates a new independent snapshot but deliberately
leaves it `ready`; review it with its status/verify command, then activate it.
Parcel `diff` requires at least two finalized parcel snapshots. Each rollback
activates the previous snapshot in its own lifecycle.

Plot lookup source selection is explicit:

```bash
dp-lookup-pro WORLI 733
# default auto: local data/mcgm-layer13.sqlite, then live fallback

dp-lookup-pro WORLI 733 --source local --database data/mcgm-layer13.sqlite
# local active snapshot only; errors if the file or active snapshot is absent

dp-lookup-pro WORLI 733 --source auto --database data/mcgm-layer13.sqlite
# local first; fall back to the existing live Layer 13 fetch if local lookup fails

dp-lookup-pro WORLI 733 --source live
# force the existing live ArcGIS path
```

The CLI default is `auto` after parcel and planning parity and end-to-end gates
passed. Auto uses explicit `--database`, then `DP_LOOKUP_DATABASE`, then
`data/mcgm-layer13.sqlite`. Strict `local` requires an explicit database path
and active parcel/planning snapshots; `live` never reads the database.

`--no-cache` still controls the existing report-result cache. It does not build,
refresh, or mutate the parcel snapshot. Snapshot selection is controlled by the
source mode and the active snapshot pointer.

## Governing data rule

> **Use verified local snapshots first; expose their date; fall back visibly.**

Layer 13 supplies local parcel identity, boundary geometry and exact adjacency.
The planning snapshot supplies local-first zoning, reservations, designations,
DP modifications, CRZ, Metro influence and optional evidence. Auto falls back
to live planning when the snapshot is missing, invalid, query-failing or older
than 210 days. Strict local can use stale data only with a clear warning. Road
edge/name/width probes, DP map rendering and satellite imagery remain live.

The local database is an audited copy of an official source, not itself a legal
authority. Reports show both snapshot IDs/dates and whether any live fallback
was used.

## Completed first-build reliability record

Snapshot 1 was built and activated locally on 2026-08-21. The generated file is
ignored by Git. Its recorded content hash is
`4ce5af608b211f4b9f6e6921927d49848830bdcb8d1084c20f98ae8190ebef97`.
The detailed evidence is retained in
[`audits/LOCAL-FIRST-VALIDATION-2026-08-21.md`](audits/LOCAL-FIRST-VALIDATION-2026-08-21.md).
The completed checks were:

- all 135,342 inventory IDs exactly matched the stored parcel IDs;
- geometry, JSON, foreign-key, SQLite and R-Tree validation passed without an
  error or warning;
- duplicate village/CTS groups were reported rather than deduplicated;
- 15 seeded ObjectIDs matched the immediate live Layer 13 raw feature,
  attributes and geometry exactly, and the full live inventory matched;
- offline multipart, topology, failure, activation and rollback contracts pass;
- an interrupted transport attempt left the partial snapshot non-active and the
  corrected POST build resumed the same persisted inventory;
- an end-to-end local WORLI 733 lookup completed with local planning evidence
  and exact spatial-database neighbours CTS 733A and 734;
- five paired auto/live end-to-end cases produced every exporter successfully.
  Ordinary single-part cases matched planning results. Multipart cases were
  intentionally more complete locally because auto combines every Layer 13
  source part while the legacy live query selects its first returned feature;
  reports now disclose the part count and combined-geometry scope;
- the later planning activation gate matched live core results on 15/15 CTS
  cases and full optional evidence on 5/5 cases;
- three fresh CLI cases used local core and optional planning evidence, returned
  no warning and generated all seven artifacts; and
- the full project suite passes 399 tests at 84.48% branch-aware coverage, with
  strict mypy and Ruff clean.

The CLI now defaults to `auto` after expanded parity and stress testing. Keep
the forced-live escape hatch and programmatic live default until longer-term
field use covers more reviewed irregular/multipart cases.

## Storage and later work

The active combined database is about 1.0 GiB after removing the failed partial
planning attempt and compacting SQLite. It contains the 536 MiB parcel snapshot
plus the complete planning archive, canonical raw source features, query-ready
attributes, exact geometry and spatial indexes. The application does not
currently publish or host the database online. A future storage optimization
can losslessly compress raw audit JSON, and a cloud repository can implement
the same source contracts after local updates are proven.

The derived [plot-intelligence database](PLOT_INTELLIGENCE.md) now builds on
this foundation with village/ward/area/planning searches, one-plot dossiers,
site comparison, local road/access analysis and refresh-alignment checks.
Future work can add:

- plot assemblies and amalgamation studies beyond the present adjacency facts;
- automated scheduler installation around the documented biannual refresh;
- deterministic feasibility, FSI and massing inputs;
- cloud storage or a server repository.

None of those features changes the present safety boundary: no incomplete
snapshot is active, local evidence always exposes snapshot provenance, and a
cached report is never presented as a fresh source query.
