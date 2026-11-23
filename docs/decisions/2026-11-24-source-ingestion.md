# MCGM source ingestion and snapshots

**Date:** 2026-11-24
**Status:** Accepted
**Affects:** `dp_lookup/application/database_services.py`,
`dp_lookup/application/planning_database_services.py`,
`dp_lookup/application/snapshot_ingestion.py`, `dp_lookup/application/planning_snapshot.py`,
`dp_lookup/application/upstream_check.py`, `dp_lookup/clients/planning_evidence_queries.py`,
`dp_lookup/planning_evidence/registry.py`, `dp_lookup/planning_snapshot/`,
`dp_lookup/spatial_store/store.py`, `tests/test_dp_lookup.py`

Moved from code comments; see [2026-11-24 no code comments](2026-11-24-no-code-comments.md).

## Be gentle with a public service

- Snapshot builds send one sequential request every ~2 s (Layer 13) and pause
  at least 0.25 s between planning batches. Builds still finish in minutes.
- The snapshot importer owns retry and backoff. The shared HTTP client it
  uses gets one transport attempt per importer attempt, so the two retry
  loops never multiply into up to nine requests.
- Large ObjectID lists are sent with POST so URL length limits cannot reject
  an otherwise valid batch.

## Resume and completeness

- The SQLite inventory and stored ObjectIDs are the primary resume proof. An
  external checkpoint is read only when the caller supplies one explicitly, so
  a stale checkpoint from an older completed snapshot is never reused.
- A caller-provided checkpoint alone cannot prove that skipped records still
  exist; a durable sink may prove them through `on_inventory`.
- An ID missing from a successful response is not treated as complete. It
  stays in `missing_ids` and is eligible for a later resume. `rejected_ids` is
  only for malformed features or exhausted requests.
- An incomplete result is still returned (with `manifest.complete` false) so
  the caller can persist the checkpoint and retry.
- Source-inventory drift makes a partial planning snapshot unsafe to resume,
  so it is failed. Any other failure keeps the building snapshot so a later
  command can continue from its durable feature IDs.
- A failed snapshot version is kept with its diagnostics. Evidence is never
  deleted, and a partial snapshot never becomes eligible for activation.
- An inventory record with empty source geometry is preserved exactly and
  kept out of spatial hits, rather than silently dropping its ObjectID.
- Planning features are materialised once per layer so generators give an
  authoritative count and split into bounded, atomic batches.

## Archive everything, query an allow-list

The durable snapshot keeps every published attribute, so a future feature
never needs a destructive re-download to expose a field. Runtime evidence
queries, live and local, return only the audited field subset, so local mode
cannot leak unrelated or schema-drift fields.

## Canonical layers

- Some map-service layers are aliases of others (`CANONICAL_LAYER_IDS`, for
  example 57 → 61). Only the canonical layer is queried; the mapping keeps the
  audit trail explicit when a caller starts from an alias. The first canonical
  source contract stored for a layer is preserved; aliases only enrich its
  provenance.
- The first group in `LAYER_SPECS` documents the current lookup contract. The
  optional evidence service selects only the curated STANDARD/FULL layers. It
  never re-queries Layer 13 or replaces the established planning pipeline.
- The ArcGIS request payloads asserted in `tests/test_dp_lookup.py` mirror
  requests validated against the live server. Those tests exist so a later
  tidy-up cannot silently change them.

## Upstream change checks degrade, not fail

When edit-time metadata is unavailable, the upstream check still compares
inventory and schema and records that edit-time evidence was missing.

## SQLite indexes

- `ANALYZE` runs after every planning snapshot so the planner picks the
  narrow spatial indexes immediately after a bulk refresh. It changes only
  planner statistics, never archived attributes or geometry.
- SQLite builds without the R*Tree module stay correct by using the indexed
  bounding-box columns on `parcels`.
