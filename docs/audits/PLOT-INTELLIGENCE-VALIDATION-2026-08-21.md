# Plot-intelligence validation — 2026-08-21

> Historical validation note: this audit records the earlier `cos(latitude)^2`
> implementation. The current shared area assessment transforms parcel
> coordinates to UTM zone 43N and applies 2%, 5% and 10% discrepancy checks.

## Scope

This audit validates the derived-data lifecycle and real workflow commands
against the active local source database. It does not claim that a full
119,519-identity intelligence build has been published.

## Active source baseline

- Parcel snapshot: 1
- Planning snapshot: 2
- Layer 13 features: 135,342
- Queryable village/CTS identities: 119,519
- Planning archive: 52 canonical layers, 65,604 records
- Intelligence algorithm: `plot-intelligence/1.1.0`

## Real-data derivation sample

Build 6 processed 25 contiguous identities beginning at deterministic offset
50,000 with full evidence, local road analysis and local adjacency enabled.

- State: ready sample; deliberately non-activatable
- Derived records: 25/25
- Source references: 92
- Derivation errors: 0
- Verification errors: 0
- Records with adjoining plots: 25/25
- Records with a mapped nearby road: 23/25
- Confidence: 15 verified-source, 10 qualified-with-warnings, 0 review-required

The ten qualified records retained unusually different recorded plot and
calculated boundary areas, mainly subdivision identities carrying a repeated
parent-area value. They were not silently promoted to verified-source.

The audit found and corrected an initial false quality signal: raw EPSG:3857
area is inflated at Mumbai's latitude. Algorithm 1.1.0 applies the local
`cos(latitude)^2` area scale before labelling geometry or overlap values as
square metres. GUNDAVALI CTS 345 then measured 1,262.66 m² from geometry against
the official 1,256.59 m², a 0.48% difference, and correctly became verified.

## Workflow verification

- `analyze GUNDAVALI 345` returned zone R, recorded plot area 1,256.59 m²,
  calculated boundary area 1,262.66 m², five neighbours, an 18.3 m road and a
  complete source lineage with facts hash.
- Structured search returned only records matching zone, minimum area,
  reservation and encumbrance filters.
- Comparison returned GUNDAVALI CTS 345 and 351 side by side with no missing
  identities.
- A normal strict-local lookup for GUNDAVALI CTS 367 used local road evidence
  (`M. V. Road From Andheri Station to Highway.`, `27.45M`) and completed its
  data/vector stages in a 1.90 s total application run. The live DP base-map
  image endpoint was unavailable during that run, so the report correctly
  remained incomplete rather than caching a blank map. This was unrelated to
  local parcel, planning or road evidence.

## Publication performance

A four-worker, 100-identity full-evidence benchmark completed 100/100 with zero
errors and 493 source references in 98.59 s. Exact full evidence remains roughly
one second per identity on this workstation; a citywide publication is
therefore estimated at 30–36 hours. SQLite write serialization and geometry
work limited the four-thread wall-time improvement.

The full publication was not started automatically. Build 6 is retained as the
single audit sample; older experimental samples were removed. No intelligence
build is active, so existing lookup behavior cannot accidentally depend on a
partial dataset. The builder is resumable, but a set-based spatial-enrichment
pass is recommended before the first full publication.

## Quality gates

- Tests: 399 passed
- Branch-aware coverage: 84.48% (80% gate)
- Ruff: clean
- Strict mypy: clean across 41 source modules
- Architecture dependency checks: passed
- Documentation contracts: passed
