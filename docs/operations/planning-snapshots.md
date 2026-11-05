# Local planning-layer snapshot contract

**Status:** Implemented; refreshed planning snapshot verified and active
**Updated:** 2026-10-23

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
dp-lookup-pro db planning build
dp-lookup-pro db planning status
dp-lookup-pro db planning verify
dp-lookup-pro db planning activate
dp-lookup-pro db planning rollback
```

The older `database build-planning`, `status-planning`, and related forms remain
supported. `db check-upstream` compares all active planning-layer schemas, edit
signals and ObjectID inventories without downloading feature geometry. It can
therefore avoid an unnecessary six-month rebuild when no change is detected;
an annual full rebuild remains the final verification backstop.

`build-planning` creates or resumes a `building` snapshot and leaves a complete
result `ready`. Verification is explicit; activation is a separate atomic
pointer switch. A failed or incomplete build can never become active.

To refresh only changed layers, supply their canonical IDs:

```bash
dp-lookup-pro db planning build --layers 81,85,92,192,194,2400
dp-lookup-pro db planning verify
dp-lookup-pro db planning activate
```

This creates a new complete snapshot. It copies other layers byte-for-byte
from the active snapshot locally, including their inventories and source
metadata, and downloads geometry only for the selected layers. Copied layers
record their originating snapshot. The active snapshot stays unchanged until
explicit activation; its old records remain available for rollback.

Before and after the targeted download, lightweight checks compare inventories,
schemas and available edit signals for every layer. An omitted changed or
unknown layer prevents publication. Source drift invalidates a staged build;
resumption requires the same base snapshot, selected layers and fingerprints.
Incremental builds cannot resume an unrelated full build or external checkpoint.
Matching signals cannot prove every coordinate under an existing ObjectID is
unchanged, so retain the annual full-verification backstop. Copied payloads
retain their original source provenance rather than claiming a new download.

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

Road names, recorded widths and proximity are calculated from local planning
road layers when available; live probes remain the fallback. Rendered DP map
backgrounds and satellite imagery use online services.

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
validation record](../audits/PLANNING-SNAPSHOT-VALIDATION-2026-08-21.md).

## Current active snapshot

The targeted 2026-10-23 update activated planning snapshot 5 with 52/52
canonical layers and 65,624/65,624 records. Its content hash is
`641a46b40eff199280d8f2c8e00a28bb40f9ed9d6fe0a89b81e555fce8e1bcd2`.
Layers 81, 85, 92, 192, 194 and 2400 were downloaded; the remaining 46 were
copied from snapshot 3 with identical content hashes. The six layers contain
26 added records and one edited existing record. All 27 added/edited payloads
match the live service exactly. See the
[targeted update record](../audits/TARGETED-SOURCE-UPDATE-2026-10-23.md).
