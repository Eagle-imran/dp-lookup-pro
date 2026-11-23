# Caching, locking and concurrency

**Date:** 2026-11-24
**Status:** Accepted
**Affects:** `dp_lookup/clients/cache.py`, `dp_lookup/clients/tile_cache.py`,
`dp_lookup/exporters/excel.py`, `dp_lookup/application/image_artifacts.py`,
`dp_lookup/planning_snapshot/query.py`, `dp_lookup/core/topology.py`

Moved from code comments; see [2026-11-24 no code comments](2026-11-24-no-code-comments.md).

## Result cache and Excel register locking

- Several lookups in one process, or two CLI runs started from a script, can
  touch the same cache file. A process-local `RLock` is the real guard and
  works on every platform. The file lock (`fcntl`, or `msvcrt` on Windows) is
  only a best-effort extra for cooperating processes.
- If the file lock cannot be taken or released, the cache and register stay
  usable under the process-local lock.
- `msvcrt.locking` locks bytes, so the lock file is given one byte first.
- Output directories are resolved with `realpath`, so aliases such as
  `reports/../reports` or a symlink cannot split one cache into two in-memory
  stores.
- Writes re-read the store from disk while holding the lock, so two
  processes writing different keys cannot overwrite each other with stale
  snapshots. When saving a whole store, entries another process wrote are
  kept, and keys present in the caller's store win (the historical
  "mutate then save" contract).
- A failed save never leaves a misleading temporary cache file behind.

## Satellite tiles

Imagery is refreshed upstream. A disk tile older than 30 days is fetched
again; the old tile is used only when that refresh fails.

## Concurrency and performance

- The DP map and satellite renderers use independent inputs and write
  nothing, so they run concurrently before the shared save step. Each keeps
  its own warning list, merged in output order so diagnostics stay
  deterministic.
- A single CRZ feature can contain hundreds of rings. Ring-containment depth
  uses an `STRtree` so each ring is only tested against plausible containers
  instead of every larger ring (previously quadratic).
- Local planning queries attach the already validated Shapely polygon to each
  candidate as an in-process acceleration, so large CRZ/Metro geometries are
  not decoded twice in one lookup. The exact source rings are still returned
  unchanged.
