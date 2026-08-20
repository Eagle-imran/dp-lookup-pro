# Planning snapshot validation — 2026-08-21

## Decision

Planning snapshot 2 is safe to use as the CLI's primary planning source. It is
active in `data/mcgm-layer13.sqlite`; `auto` retains a visible live MCGM
fallback. Road probes, rendered DP maps and satellite imagery remain live.

## Completeness and integrity

- Canonical layers: 52/52
- Official inventory records: 65,604
- Stored records: 65,604
- Missing, rejected or extra IDs: 0
- Validation errors: 0
- Store hash: `075ed239f004c968d3ba33e465d2606109f6e04def8efc347556e20949a0dbb6`
- Download/build time: 3.68 minutes
- Active planning snapshot: 2
- Active parcel snapshot: 1 (independent lifecycle)

Three source records are complete but non-spatial: Designation layer 47
ObjectIDs 1158, 1159 and 4817 contain empty official rings. Verification keeps
them as warnings and does not invent geometry or discard their attributes.

The first download attempt exposed official schema differences and remained
failed/non-active. Metro influence zones, traffic road alignments and water
bodies publish `OBJECTID_1`, not the registry's earlier `OBJECTID` default. The
corrected importer discovers the OID and geometry type from official metadata.
After snapshot 2 passed activation and end-to-end checks, failed snapshot 1 was
removed and SQLite was compacted from 1.6 GiB to 1.0 GiB.

## Live/local semantic parity

The deterministic seed was `20260821`. Each case was selected from the active
parcel snapshot by village/CTS identity. Only those public identifiers were
sent to MCGM; the audit fetched parcel geometry from live Layer 13 and supplied
that identical official geometry to both planning engines.

Core planning matched on all 15 cases: BANDRA-EAST 32/40; VILE PARLE 287;
KOLEKALYAN 1791D; ERANGAL 1719/2; KOLEKALYAN 1434; MAJAS 133; FORT 1795;
EKSAR 2539; MANORI 1151; CHEMBUR 173; MAZAGAON 449; EKSAR 894; KANDIVALI
430; MOGRA 16; and GHATKOPAR KIROL 3931.

- Core result equality: 15/15
- Full optional-evidence equality: 5/5 (the first five cases)
- Core median: 215.3 ms live, 161.7 ms local
- Full-evidence median: 575.0 ms live, 1,364.8 ms local

Equality excluded only source/timing provenance. Zones, reservations,
designations, modifications, CRZ, Metro state, overlaps, outcome states,
findings, authority classes, summaries and warnings were compared. There were
no semantic differences. The full local path spends most of its time decoding
a very large exact CZMP multipart polygon; it remains bounded and avoids the
availability risk of 27 live layer requests.

The spatial implementation was optimized before the final audit: SQLite now
starts with its R-Tree candidate search, and multipart ring containment uses a
spatial tree instead of quadratic pairwise checks. A representative local full
scan fell from about 4.4 seconds to about 0.57 seconds in isolation while
preserving exactly equal geometry.

After activation, cleanup and compaction, a five-case database-only benchmark
measured a 64.5 ms median for core planning and 603.8 ms for full optional
evidence. These are component timings, not promises for the complete seven-file
bundle; live roads, map rendering and satellite imagery still dominate a cold
end-to-end run.

## Real CLI acceptance

Fresh `auto --no-cache` runs for WORLI 733 (`full`), COLABA 1/600 (`standard`)
and VILE PARLE 1449 (`full`) all returned:

- exit code 0 and `metadata.complete: true`;
- core planning provenance `local_snapshot`;
- optional evidence provenance `local_snapshot` and complete evidence;
- no result warnings; and
- all seven bundle artifacts, plus the shared Excel register.

## Engineering gates

- Ruff: clean
- Strict mypy: clean across 35 production modules
- Tests: 399 passed
- Branch-aware coverage: 84.48% (80% gate)
- Generated database: 1.0 GiB, ignored by Git

Raw parity JSON and generated acceptance bundles were retained under `/tmp`
during the run. This file is the durable project audit record. Repeat the
inventory, verification and parity gates before activating every future
biannual refresh.
