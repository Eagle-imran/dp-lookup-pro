# Lookup performance audit — 2026-08-24

This audit records the first speed-focused pass after local-first operational
acceptance. No ArcGIS ingestion field, source geometry, planning policy or
output contract was changed.

## Fixed corpus and method

The before and after runs used the same five accepted identities:

- WORLI 733
- COLABA 1/600
- BYCULLA 1605
- CHARKOP 566
- VILE PARLE 1449

Each fresh run used the normal implicit `auto` source, the configured local
database, `--no-cache`, a unique output root and BASIC evidence. Each completed
fresh run was immediately repeated through the normal report-result cache.
All ten runs in each pass exited successfully and produced the complete
seven-artifact contract.

These are warm operational measurements. `--no-cache` disables the report
cache, but the independently managed satellite-tile cache and operating-system
SQLite page cache remain available as they would during ordinary internal use.
MCGM DP-map response time remains externally variable.

## Before and after

| Metric, five-run median | Before (2026-08-23) | After | Change |
| :--- | ---: | ---: | ---: |
| Answer visible | 0.70 s | **0.40 s** | **43% faster** |
| Complete seven-file bundle | 2.40 s | **1.60 s** | **33% faster** |
| Complete CLI process | 2.85 s | **2.08 s** | **27% faster** |
| Cached CLI process | 0.37 s | 0.41 s | No material change; startup dominated |
| Cache file read | 5.1 ms | 6.4 ms | No material change |

After the pass, the five answers ranged from **0.20–0.50 seconds** and complete
bundles from **1.30–2.00 seconds**. The fresh-answer target was met across the
corpus, and every operational bundle completed in two seconds or less.

## Changes responsible

1. Successful parcel and planning snapshot finalisation now runs SQLite
   `ANALYZE`. This persists derived planner statistics without changing source
   rows or geometry. On the active database, an exact WORLI 733 parcel lookup
   fell from a 142.15 ms median to 0.031 ms because SQLite selected the intended
   village/CTS index instead of scanning the snapshot key.
2. Local planning selection retains an in-process Shapely object alongside the
   unchanged source rings. Planning normalisation and optional evidence reuse
   that object instead of decoding very large CRZ and Metro polygons twice.
3. Road screening uses a compact planning read that omits the archived raw
   feature JSON while retaining attributes and exact geometry.
4. The CLI composition root owns one parcel-store connection per lookup and
   shares it with parcel and neighbour adapters.
5. DP and satellite rendering run concurrently. PDF, Excel and optional report
   writers retain deterministic invocation order after both images are safely
   written.
6. Every result now includes additive `diagnostics.spans_ms` timings inside the
   established stage timings, and an offline injected-delay regression test
   protects the concurrency and stage budgets.
7. Admin and experimental namespace dispatch moved behind a small lazy router,
   keeping the normal lookup CLI independent from optional command modules.

## Remaining latency

A representative post-change WORLI 733 run took 1.36 seconds inside the lookup
service. The largest measured boundaries were:

- DP-map fetch: approximately 0.87 seconds;
- report rendering/writers: approximately 0.39 seconds;
- vector exporters: approximately 0.11 seconds;
- local spatial planning: approximately 0.09 seconds; and
- local road analysis: approximately 0.06 seconds.

The next speed work should therefore target reusable visual assets and derived
geometry acceleration only if freshness/provenance remain explicit. Further
micro-optimising exact parcel SQL would not materially improve user-visible
latency.

## Final verification

- 539 tests passed at 84.21% branch-aware coverage.
- Ruff and strict package-wide mypy passed.
- Source and wheel distributions built successfully.
- The five-case local-first benchmark completed 5/5 fresh and 5/5 cached runs.
- A forced-live WORLI 733 smoke lookup completed against MCGM ArcGIS and wrote
  all seven output files, confirming that this pass did not replace or bypass
  the live fallback.
- The fixed corpus retained equal plot identity, planning remarks and area
  assessment data, with byte-identical GeoJSON geometry against the accepted
  pre-change baseline.
