# Plot intelligence database

**Status:** Implemented; representative builds verified. A full citywide build
must be verified and explicitly activated before it becomes the default search
source.

## Purpose and authority boundary

Plot intelligence turns the immutable parcel and planning archives into one
query-ready record per unique `VILLAGE + CTS_CS_NO` identity. The active MCGM
cadastral parcel archive currently contains 135,345 source features representing
119,522 queryable village/CTS identities. Multipart source features are
combined; they are not counted as separate plots. The technical ArcGIS
provenance is retained as Development Plan Layer 13.

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
        + versioned authority registry
        ↓ deterministic spatial analysis + explicit active selections
plot-intelligence build
        ↓ explicit verification + activation
analyze / search / compare
```

Source snapshots are never changed by intelligence generation. An intelligence
build is tied to exactly one finalized parcel snapshot, one finalized planning
snapshot, the authority-registry revision, a source fingerprint and
`plot-intelligence/1.4.0`. Re-running a
matching interrupted build resumes completed identities. Publishing switches an
active pointer; it never edits an earlier build.

Resumption also requires the same selected range, evidence mode and neighbour
option. Activation and default queries require current source, authority and
algorithm fingerprints. Use an explicit `--build-id` to inspect a historical
build without treating it as current. An authority change during derivation
fails the build so mixed source selections cannot be published.

Normal plot lookup reads the source snapshots directly; it does not query this
derived build or require intelligence activation. The retained validation build
6 is a 25-identity sample using parcel snapshot 1, planning snapshot 2 and
algorithm 1.1.0. It cannot be activated. The active source baseline is now parcel
snapshot 2 and planning snapshot 3; a fresh full build with the current algorithm
is required for citywide search.

## Stored facts

Each plot record contains:

- identity, ward, all source ObjectIDs and multipart count;
- recorded plot area, calculated boundary area and the basis used for each;
- zoning overlaps, reservations, designations and DP modifications;
- CRZ and Metro screening, encumbered percentage and net area;
- nearest mapped road, width, distance, source layers and ObjectIDs;
- exact adjoining CTS identities when neighbour analysis is enabled;
- full curated due-diligence summary and applicability flags;
- confidence, warnings, calculation timestamp and deterministic facts hash;
- normalized source references back to the official service records.

Raw geometry and complete ArcGIS payloads remain only in the canonical snapshot
tables. Intelligence records reference them rather than duplicating the archive.

The recorded plot area and calculated boundary area are both retained because
they can disagree even though ArcGIS delivers both. The recorded value is an
attribute in the MCGM cadastral parcel record; the calculated value comes from
the supplied polygon coordinates. Area totals use the recorded value when it is
available, while spatial overlap percentages use the boundary geometry.
Boundary coordinates are transformed from Web Mercator to WGS 84 and then UTM
zone 43N before area is calculated in square metres. Differences above 2%, 5%
and 10% receive progressively stronger deterministic quality flags.

## Reliability labels

Reliability labels describe the evidence available to the tool; they are not
legal conclusions:

| Label | Meaning |
| :--- | :--- |
| **Screening** | Suitable for early feasibility and site review, subject to the displayed source limits. |
| **Verified source** | The source record, identity and archived payload passed the tool's deterministic completeness and provenance checks. This does not mean the boundary was legally surveyed. |
| **Qualified with warnings** | The result is usable for review, but an area difference, geometry issue, duplicate record or identity ambiguity needs attention. |
| **Certified** | The shared area assessment can assign this only when area and geometry both have clean, explicitly activated certified evidence. An ArcGIS parcel alone never receives this label. |

The intelligence search column uses `verified`, `qualified` and
`review_required` confidence values. The richer area-reliability label is
preserved separately in `evidence_summary.area_assessment`; it is not a legal
conclusion or an additional search-confidence value.

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

The 2026-10-23 development pass measured 1,000 full-evidence identities in
32.107 seconds with one worker, versus 41.383 seconds with four. The default is
now one worker; `--workers` remains available. A bounded, snapshot-scoped
planning cache reuses source geometries without changing archived records.
See [development status](../project/development-status.md) for the measured
scope and publication progress.

Single-record analysis and structured searches are fast once a build exists.
The first full build performs exact intersections against the complete evidence
registry and is deliberately resumable. A measured four-worker, 100-identity
run on 2026-08-21 took 98.59 seconds, giving a historical 30–36 hour citywide
estimate. Later database and geometry optimizations have not been rebenchmarked
for a full intelligence publication. Measure a fresh representative sample
before scheduling the full job. It is an offline publication job, not a
request-time operation.

The real-data results are recorded in the
[plot-intelligence validation audit](../audits/PLOT-INTELLIGENCE-VALIDATION-2026-08-21.md).
