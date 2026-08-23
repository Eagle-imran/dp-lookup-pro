# Offline stage-latency regression

The project has a deterministic, network-free latency gate in
`tests/test_stage_latency_regression.py`. It runs the real lookup coordinator
through `LookupDependencies`, while replacing the ArcGIS, artifact and render
adapters with small fakes that inject a repeatable 15 ms delay.

Run it with:

```bash
uv run pytest -q tests/test_stage_latency_regression.py
```

The harness checks that the result remains complete and that the diagnostics
stage timings stay within these budgets:

| Stage | Injected-delay floor | Regression ceiling |
| :--- | ---: | ---: |
| Parcel ingestion | 10 ms | 150 ms |
| Concurrent source queries | 10 ms | 250 ms |
| Vector artifacts | 10 ms | 300 ms |
| Report artifacts | 20 ms | 400 ms |
| Complete-stage mark | — | 100 ms |
| Whole run | — | 1,000 ms |

Every result also carries additive `diagnostics.spans_ms` timings for the
replaceable boundaries inside those stages: parcel fetch/normalisation,
neighbour and road providers, planning identify/query/evidence, vector
exporters, DP-map and satellite fetches, remaining visual wait, total visual
fetch and report rendering. Spans do not alter the established sequential
`stages_ms` contract, so they can be compared independently.

After a successful parcel or planning snapshot build, the stores run SQLite
`ANALYZE`. This records derived query-planner statistics only—it does not alter
archived attributes or geometry. The step prevents a fresh citywide database
from scanning an entire snapshot when the exact village/CTS index is available.

The lower bounds make sure the delayed adapters are actually exercised. The
ceilings are deliberately generous for CI variance and are intended to catch
stage serialization, runaway geometry work or an accidental blocking call—not
to claim production latency.

This is an offline regression gate, not a live MCGM benchmark. It does not
measure ArcGIS availability, network variance, tile-server performance or
client-facing cold lookup time. Current live and historical measurements stay
in the dated audit records and changelog. When a threshold fails, inspect the
stage diagnostics first, then run the live smoke/acceptance audit separately.

The harness must remain adapter-based: do not add sleeps or benchmark-only
branches to `lookup_service.py`, telemetry, CLI, stores or query modules.
