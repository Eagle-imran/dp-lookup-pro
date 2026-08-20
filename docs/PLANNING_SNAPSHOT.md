# Local planning-layer snapshot contract

**Status:** Implemented; first complete planning snapshot verified and active
**Updated:** 2026-08-21

## Purpose and boundary

The planning snapshot makes zoning, reservations, designations, modifications,
CRZ, Metro influence and optional due-diligence evidence available from a
repeatable local source. It uses the audited planning registry and excludes
Layer 13, which has its own parcel builder.

Parcel and planning data live in the same SQLite file for simple operation, but
their tables, snapshot IDs, active pointers, validation and rollback lifecycles
are independent. Rebuilding planning data cannot replace the active parcel
snapshot, and vice versa. The database is an audited copy of official MCGM data;
it is not itself an official DP Remark or legal certificate.

## Build and verification commands

```bash
dp-lookup-pro database build-planning    --database data/mcgm-layer13.sqlite
dp-lookup-pro database status-planning   --database data/mcgm-layer13.sqlite
dp-lookup-pro database verify-planning   --database data/mcgm-layer13.sqlite
dp-lookup-pro database activate-planning --database data/mcgm-layer13.sqlite
dp-lookup-pro database rollback-planning --database data/mcgm-layer13.sqlite
```

`build-planning` creates or resumes a `building` snapshot and leaves a complete
result `ready`. Verification is explicit; activation is a separate atomic
pointer switch. A failed or incomplete build can never become active.

## Ingestion contract

`dp_lookup.application.planning_snapshot` resolves duplicate aliases such as
57/61 and 2251/2250 before network work, then processes every canonical layer:

1. Read official layer metadata and discover the actual ObjectID and geometry
   fields. The metadata is authoritative when a registry default differs.
2. Request the complete ObjectID inventory with `returnIdsOnly=true`.
3. Fetch sequential, bounded POST batches with `returnGeometry=true` and
   `outSR=102100`; retries are bounded and honor `Retry-After`.
4. Persist each accepted batch atomically and resume only when the exact source
   inventories and registry hash still match.
5. Prove set equality: every inventory ID must be present, with no missing,
   rejected, extra or failed batches.
6. Hash and finalize every layer, then finalize the top-level snapshot only
   when every canonical layer is complete.

The archive deliberately requests `outFields=*` so a future audit can inspect
all official source fields without another download. Runtime optional evidence
still filters archived attributes through the registry's explicit allow-list,
exactly like the live query path. This keeps archival completeness separate
from what is permitted into a report.

The downloader is storage-agnostic. `on_inventory` reports already durable
ObjectIDs and `on_batch` writes one accepted batch. The SQLite adapter persists
the detailed checkpoint and manifest beside the database. Generated database,
checkpoint and manifest files are ignored by Git.

## Runtime source policy

In CLI `auto`, an active planning snapshot is queried first. One snapshot ID is
pinned for the entire lookup, and every local feature goes through the same
intersection, sliver, authority and result parser as live ArcGIS. Results expose
snapshot ID, timestamp, age and source under `metadata.evidence`.

- `auto`: local first; visibly fall back to live planning when missing, invalid,
  query-failing, or older than 210 days.
- `local`: require local planning data; stale data is allowed only with a clear
  warning so an offline lookup remains possible.
- `live`: bypass the planning snapshot.

Road edge/name/width probes, rendered DP maps and satellite imagery remain live.
They use separate road and rendering services and are not supplied by this
planning snapshot.

## First complete snapshot record

The 2026-08-21 build completed in 3.68 minutes:

| Check | Result |
| :--- | :--- |
| Canonical planning layers | **52 / 52** |
| Source records | **65,604 / 65,604** |
| Validation errors | **0** |
| Source-geometry warnings | **3** |
| Active snapshot | **2** |
| Store content hash | `075ed239f004c968d3ba33e465d2606109f6e04def8efc347556e20949a0dbb6` |

The three warnings are official Designation records 1158, 1159 and 4817 whose
source features have empty polygon rings. They are retained for inventory and
attribute authority but cannot produce a spatial intersection. Empty official
geometry is a warning, not an invented polygon and not a missing record.

The build also found three registry/source ObjectID-name differences and now
discovers them from official metadata: Metro influence zones, traffic road
alignments and water bodies publish `OBJECTID_1` rather than `OBJECTID`.

The activation gate compared 15 deterministic CTS cases against live MCGM core
planning and five of those against full optional evidence. All core results
were equal (15/15) and all full-evidence reports were equal (5/5), ignoring only
source/timing provenance. Three subsequent real CLI runs completed without a
warning and produced all seven artifacts. See the durable [planning snapshot
validation record](audits/PLANNING-SNAPSHOT-VALIDATION-2026-08-21.md).
