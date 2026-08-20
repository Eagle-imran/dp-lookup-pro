# Plot intelligence database

**Status:** Implemented; representative builds verified. A full citywide build
must be verified and explicitly activated before it becomes the default search
source.

## Purpose and authority boundary

Plot intelligence turns the immutable parcel and planning archives into one
query-ready record per unique `VILLAGE + CTS_CS_NO` identity. The active source
archive currently contains 135,342 Layer 13 features representing 119,519
queryable village/CTS identities. Multipart source features are combined; they
are not counted as separate plots.

The database can be the project's **internal operational system of record**.
It is not a statutory declaration and cannot replace MCGM, the sanctioned DP,
title documents, survey records or competent-authority decisions. Its strength
is reproducibility: every fact identifies the parcel snapshot, planning
snapshot, algorithm version, source layer and ObjectID that produced it.

## Three immutable levels

```text
official ArcGIS service
        ↓ inventory + complete raw payload
parcel snapshot + planning snapshot
        ↓ deterministic spatial analysis
plot-intelligence build
        ↓ explicit verification + activation
analyze / search / compare / normal lookup
```

Source snapshots are never changed by intelligence generation. An intelligence
build is tied to exactly one finalized parcel snapshot, one finalized planning
snapshot, a source fingerprint and `plot-intelligence/1.1.0`. Re-running a
matching interrupted build resumes completed identities. Publishing switches an
active pointer; it never edits an earlier build.

## Stored facts

Each plot record contains:

- identity, ward, all Layer 13 source ObjectIDs and multipart count;
- approved area, digitized geometry area and the basis used for each total;
- zoning overlaps, reservations, designations and DP modifications;
- CRZ and Metro screening, encumbered percentage and net area;
- nearest mapped road, width, distance, source layers and ObjectIDs;
- exact adjoining CTS identities when neighbour analysis is enabled;
- full curated due-diligence summary and applicability flags;
- confidence, warnings, calculation timestamp and deterministic facts hash;
- normalized source references back to the official service records.

Raw geometry and complete ArcGIS payloads remain only in the canonical snapshot
tables. Intelligence records reference them rather than duplicating the archive.

Approved and digitized areas are both retained because they can disagree. Area
totals use the approved value when published; spatial overlap percentages use
the digitized geometry. EPSG:3857 planar areas are corrected by the local
`cos(latitude)^2` scale before they are labelled square metres. A remaining
difference above 5% is visibly qualified.

## Commands

```bash
# A small non-publishable validation run
dp-lookup-pro intelligence build --database data/mcgm-layer13.sqlite \
  --limit 25 --no-neighbours --json

# Full resumable build; full evidence and neighbours are defaults
dp-lookup-pro intelligence build --database data/mcgm-layer13.sqlite
dp-lookup-pro intelligence verify --database data/mcgm-layer13.sqlite
dp-lookup-pro intelligence activate --database data/mcgm-layer13.sqlite

# One dossier, database-wide filters and side-by-side comparison
dp-lookup-pro intelligence analyze WORLI 733 \
  --database data/mcgm-layer13.sqlite --json
dp-lookup-pro intelligence search --database data/mcgm-layer13.sqlite \
  --zone R --min-area 2000 --has-reservation no --max-encumbered 10
dp-lookup-pro intelligence compare WORLI:733 COLABA:1/600 \
  --database data/mcgm-layer13.sqlite --json

# Snapshot age and active-version alignment
dp-lookup-pro intelligence check --database data/mcgm-layer13.sqlite
```

Search is structured SQL, not fuzzy or vector search. Filters include village,
ward, area range, primary zone, reservation/designation presence, maximum
encumbrance and road name. Results are deterministic and ordered.

Sample builds are queryable with `--build-id` but cannot be activated. A full
build can also target finalized ready snapshots with `--parcel-snapshot-id` and
`--planning-snapshot-id`, allowing derivation and review before a new release.
Activation refuses a build whose source IDs do not match the active source
snapshots.

## Refresh and publication runbook

Run `intelligence check` monthly. Run a complete refresh at least every 183 days,
or sooner when MCGM publishes a change:

1. Build new parcel and planning snapshots without activating them.
2. Verify completeness, hashes, geometry issues and snapshot diffs.
3. Build intelligence against those finalized source IDs.
4. Review the verification report and a stratified random parity sample.
5. Activate the parcel and planning snapshots.
6. Activate the matching intelligence build immediately afterwards.
7. Run `intelligence check`; `source_alignment` must be true.
8. Retain the previous versions for audit and rollback.

A biannual rebuild compares complete source content, so it catches attribute or
geometry edits even when ObjectIDs do not change. A lightweight ObjectID-only
check cannot provide that guarantee and is therefore not treated as sufficient
publication evidence.

## Current performance note

Single-record analysis and structured searches are fast once a build exists.
The first full build performs exact intersections against the complete evidence
registry and is deliberately resumable. A measured four-worker, 100-identity
run took 98.59 seconds, giving a conservative 30–36 hour citywide estimate on
the current workstation. It is an offline publication job, not a request-time
operation. A set-based enrichment optimization should shorten that one-time job
before the first full activation without changing the schema or public commands.

The real-data results are recorded in the
[plot-intelligence validation audit](audits/PLOT-INTELLIGENCE-VALIDATION-2026-08-21.md).
