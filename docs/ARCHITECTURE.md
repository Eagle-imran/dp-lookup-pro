# Architecture and extension boundaries

`dp-lookup-pro` is a deterministic spatial lookup and evidence-export tool. The
ArcGIS services are external evidence sources; the application does not treat
a missing response as proof that a planning constraint is absent.

## Dependency direction

```text
CLI / Python facade
        |
        v
application.lookup_service (composition shell, <375 lines)
        |
        +--> ingestion --> normalization --> result_factory
        |        |               |                 |
        |        +---------------+-----------------+--> core
        |
        +--> reporting --> typed artifact registry --> exporters / renderers
        |
        +--> clients: live/local source adapters / transport / report cache
        |
        +--> spatial_store + planning_snapshot: independent immutable snapshots

        +--> authority registry: additive certified/official source versions
        |
        +--> intelligence: immutable derived facts, provenance and SQL search
        |
        +--> optional planning_evidence registry/models
                     ^
                     |
              clients.planning_evidence_queries
```

- `core` contains constants, geometry/topology, the shared area assessment,
  planning classification, and typed result models. It must not import clients,
  exporters, or renderers.
- `clients` owns external protocols: ArcGIS request/response adaptation,
  verified HTTP transport, the report-result cache, and local-first parcel and
  planning adapters. `clients.parcel_snapshot` and
  `application.snapshot_ingestion` own source extraction contracts; the
  SQLite lifecycle and queries live in `spatial_store`, below the application
  boundary.
- `planning_evidence` owns immutable due-diligence models and the audited,
  dependency-free layer registry. Its ArcGIS adapter remains in `clients`, so
  source transport cannot leak into the evidence/domain contracts.
- `intelligence` owns derived-data models, lifecycle, provenance references and
  structured queries. It imports neither clients nor application services.
  `application.intelligence_builder` is the only coordinator allowed to combine
  the two source repositories into a publishable intelligence build.
- `authority` owns versioned documents and professional-source evidence for a
  village/CTS identity. It shares the SQLite file with immutable snapshots but
  uses separate tables and activation pointers. It never mutates raw MCGM
  parcel or planning records. Authority selection is field-specific: `area`,
  `geometry`, and `planning` may each have a different active source.
- `application` coordinates one use case and isolates optional artifact
  failures. Its stage contracts are in `application/contracts.py`; concrete
  adapters are supplied through `LookupDependencies`, so tests and future UIs
  can replace boundaries without monkeypatching module globals. New workflows—
  feasibility, massing, or automated planning—belong here and should compose
  domain services rather than expand the lookup CLI.
- `exporters` and `renderers` transform an already-computed result. They do not
  decide planning status. New formats implement the `ArtifactExporter`
  protocol and register through `LookupDependencies.artifact_exporters`; the
  coordinator does not need another format-specific branch.
- `dp_lookup.core.orchestrator` is a compatibility import only. New code should
  use `dp_lookup.application.lookup_service` or the package-level API.

The boundary and compatibility facades are protected by
`tests/test_architecture_contract.py`.

## Lookup stages

| Module | Single responsibility |
| :--- | :--- |
| `core/area_assessment.py` | Recorded/calculated area separation, UTM calculation, reliability and deterministic quality flags |
| `application/ingestion.py` | Required Layer 13 parcel acquisition and validation |
| `application/normalization.py` | Road, neighbour, and planning evidence reconciliation |
| `application/output_layout.py` | Canonical, collision-free artifact paths and typed `ExportData` |
| `application/result_factory.py` | Typed contracts to stable public dictionary serialization |
| `application/exporting.py` | Typed artifact protocol, built-in adapters, and plug-in registry |
| `application/reporting.py` | Failure-isolated registry, image, PDF, and register generation |
| `application/dependencies.py` | Replaceable network/export/rendering adapter composition |
| `application/planning_evidence.py` | Optional evidence cache/result boundary without changing core completeness |
| `clients/arcgis_payloads.py` | Pure ArcGIS REST request construction |
| `clients/planning_queries.py` | Layer fetching and deterministic polygon intersection |
| `clients/planning_evidence_queries.py` | Bounded, explicit-field optional evidence queries and audit outcomes |
| `clients/tile_cache.py` | Atomic satellite tile caching |
| `clients/parcel_snapshot.py` | Layer 13 source feature and completeness contracts |
| `clients/local_parcels.py` | Active local snapshot lookup with explicit live fallback |
| `clients/local_planning.py` | Local-first core planning query with freshness guard and live fallback |
| `application/snapshot_ingestion.py` | Bounded Layer 13 inventory/batch importer and manifest |
| `application/database_services.py` | Database build/status/verify/diff/activate/rollback services |
| `spatial_store/` | Standard-library SQLite snapshots, spatial index, validation and lifecycle |
| `application/planning_snapshot.py` | Canonical planning-layer inventory/batch downloader and manifests |
| `application/planning_database_services.py` | Planning build/status/verify/activate/rollback services |
| `planning_snapshot/` | Independent planning tables, R-Tree queries, validation and lifecycle |
| `application/intelligence_builder.py` | Resumable derivation pinned to exact source snapshot IDs |
| `application/intelligence_services.py` | Analyze/search/compare/check application facade |
| `application/local_roads.py` | Deterministic local road distance, name and width evidence |
| `intelligence/` | Immutable derived builds, source references, SQL filters and activation |
| `planning_evidence/models.py` | Immutable evidence modes, findings, layer outcomes, and report |
| `planning_evidence/registry.py` | Audited layer schemas, authority classes, duplicate and applicability policy |
| `authority/` | Versioned source files, checksums, reviews, purpose-specific recommendations, activation and audit history |

## Output extension and persistence contracts

`ArtifactContext` carries immutable `ExportData`; the application no longer
passes a loosely assembled property dictionary between stages. Historical
GeoJSON, DXF, KML, and HTML writer signatures remain behind explicit adapters
so existing callers keep working. A new SVG, IFC, or massing hand-off exporter
only needs `name`, `manifest_key`, and `export(context)`. Returned artifacts are
accepted only when they are non-empty files inside the lookup bundle, keeping
manifests and cache-integrity checks trustworthy.

The HTML dossier is maintained as packaged `html_map.html`, `dossier.css`, and
`dossier.js` resources. They are embedded at export time, so each generated
report is still one HTML file. Leaflet, web fonts, and basemap tiles remain
remote runtime dependencies and require a network connection when the dossier
is opened.

The JSON lookup cache and shared Excel register both use stable sidecar locks,
same-directory temporary files, and atomic replacement. This protects
concurrent CLI processes from partial writes and lost Excel rows. The DXF
exporter exposes one frozen `DxfLayoutPolicy`; sheet geometry, labels, collision
nudges, legends, and viewport tuning can be changed and tested as one coherent
policy instead of scattered literals.

Each public result now includes field-level source evidence in
`metadata.evidence`. A successful request is distinct from confirmed evidence:
for example, an ArcGIS road placeholder is reported as unknown rather than as a
real road name, and a point-identify planning fallback makes the result visibly
incomplete instead of silently asserting that constraints are absent.

`plot_identity.area_assessment` is additive to the legacy `area_sqm` and
`area_source` fields. It preserves Recorded plot area and Calculated boundary
area separately, identifies the selected working basis, and carries the
calculation method, difference thresholds, source snapshot and reliability.
Exporters receive the same immutable assessment through `ExportData`; they do
not recalculate or reinterpret the canonical area decision.

The certified-source registry is an additive evidence layer above these
snapshots. Its lifecycle is `register -> verify -> recommend -> activate`.
Only an explicit activation for `area`, `geometry`, or `planning` affects
normal lookup. Recommendations are deterministic and field-specific;
equal-rank valid sources produce a visible conflict rather than an implicit
choice. Every source version, checksum, reviewer, selection and withdrawal is
auditable. Changing an active source changes the authority fingerprint used by
report-cache and intelligence freshness checks, so affected derived results
cannot be silently reused.

## ArcGIS ingestion contract

The current lookup depends on these MCGM Development Plan layers. Active local
snapshots satisfy parcel and polygon-planning reads; live calls remain the
fallback and the source for road probes and rendered imagery:

- base parcel: `13`
- zoning: `0` (required evidence; lookup fails closed when unavailable)
- reservation/designation/modification: `46`, `47`, `192`
- CRZ: `14`, `1264`, `1548`
- metro influence: `1550`
- roads: `193`, `194`, `44`, `45`, `2224`

Transport uses verified TLS, pooled HTTP/1.1 connections, per-request timeouts,
and bounded retry/backoff by default. HTTP/2 is deliberately not required,
keeping the runtime dependency surface smaller without changing the ArcGIS REST
contract. ArcGIS polygon rings are converted by one topology adapter, preserving
holes and multipart parcels. Mocked contract tests lock the layer set and
response behavior; a scheduled live smoke lookup detects upstream service
changes separately from deterministic pull-request CI. Its retained summary is
tri-state: `passed` after artifact validation, `upstream_unreachable` with a
workflow warning for recognized network timeouts, or a failed workflow for
reachable-but-invalid application/data responses.

Each run records a unique ID and stage timings in `metadata.diagnostics`.
`DP_LOOKUP_LOG_JSON=1` mirrors stage-completion events as JSON on stderr for
automation and incident diagnosis without coupling the library to a monitoring
vendor.

The optional planning-evidence profile runs only after the validated Layer 13
parcel is available and never re-queries it. `basic` preserves the historical
request/cache contract; `shadow` and `standard` evaluate the curated decision
and CZMP set; `full` adds wider screening sources and activates TPS, SPA, and
Gorai-Manori families only after a detector polygon intersects. In CLI `auto`
and `local`, the same deterministic parser consumes the active planning
snapshot; `auto` visibly falls back to live ArcGIS when local evidence is
unavailable, invalid, or stale. Non-basic cache keys include the evidence
profile, registry version, parcel snapshot ID, and planning snapshot ID;
incomplete optional evidence is never cached. Findings are nested under
`metadata.evidence.planning_due_diligence`, leaving the public top-level result
shape and status calculation intact.

`--no-cache` controls cache reads, not persistence: it forces a fresh source
request and a complete result replaces the relevant mode-specific cache entry.
This makes the normal workflow fast while providing an explicit refresh path
for client issues, submissions, transactions, and upstream-change validation.

## Local source snapshots

The local database is separate from the existing report-result cache. It holds
two independently activated datasets. `spatial_store.SnapshotStore` keeps
Layer 13 records in immutable
lifecycle states (`building`, `ready`, `active`, `retired`, `failed`) with
canonical raw source features, exact geometry, source manifest, validation
issues, activation history, and snapshot diffs. A build obtains and persists the
complete ObjectID inventory, commits bounded POST batches atomically, resumes
only an exact inventory match, and refuses to finalize an incomplete result.
The generated SQLite file is ignored under `data/*.sqlite`; no full snapshot is
checked into the repository. The first workstation-local snapshot was built,
verified, live-sampled and activated on 2026-08-21. The CLI now defaults to
local-first `auto`; the programmatic dependency default remains live for
backwards compatibility. `planning_snapshot.PlanningSnapshotStore` applies the
same publish-after-verification lifecycle to every canonical planning layer in
the audited registry. Both stores share one SQLite file without sharing tables,
version numbers, or active pointers.

The parcel source is selected at the CLI boundary:

```text
default / auto  -> active parcel + planning snapshots first; visible live fallback
--source live   -> bypass both snapshots for live ArcGIS source queries
--source local  -> require active local parcel + planning snapshots
--source auto   -> explicit local-first selection, optionally with --database
```

`--database PATH` is required for strict `local`. Auto resolves an explicit
path, `DP_LOOKUP_DATABASE`, then `data/mcgm-layer13.sqlite`. Local lookup combines all
source features for a village/CTS identity, so multipart or duplicate identity
groups are not silently truncated. `LocalNeighbourProvider` uses the snapshot
spatial index for candidates and Shapely for exact shared-boundary/gap tests;
its output is marked `spatial_database` and `confirmed`. Core zoning,
reservations, designations, modifications, CRZ, Metro influence and optional
evidence use exact local spatial intersections against one pinned planning
snapshot. The shared parser prevents local/live policy drift. Automatic live
fallback is visibly recorded in result notes and field evidence. Each lookup
pins both snapshot IDs, so an activation cannot mix versions during a run.

The local planning snapshot has a 210-day freshness limit in `auto`. After that
limit, auto queries live; strict local may still use the snapshot with a visible
staleness warning. Road edge/name/width analysis is now local-first against the
five archived road layers; a live boundary probe remains the visible fallback
when local road evidence is unavailable. Rendered DP imagery and satellite
tiles remain live. The programmatic dependency defaults remain live for
compatibility; the CLI assembles the local-first adapters.

Plot-intelligence builds are a third, independent lifecycle layered over the
two canonical source snapshots. A build records both source IDs, their content
fingerprint and its deterministic algorithm version. Sample builds cannot be
activated. Full activation requires completeness and active-source alignment.
See [PLOT_INTELLIGENCE.md](PLOT_INTELLIGENCE.md).

Database administration is intentionally separate from plot lookup:

```text
parcel:   database build | status | verify | diff | activate | rollback
planning: database build-planning | status-planning | verify-planning
          | activate-planning | rollback-planning
```

Activation is an explicit pointer switch, and rollback selects a previous
finalized snapshot. This gives the future city-wide search and amalgamation
features a stable repository boundary without locking the application to
SQLite, cloud hosting, or a vector database.

## Automated planning extension

Automated planning should be a separate deterministic pipeline with explicit
inputs and outputs:

```text
LookupResult + client brief + rule set
                  |
                  v
buildable-envelope solver -> candidate generator -> constraint evaluator
                  |                                  |
                  +------------> ranked plans <------+
```

Recommended components:

1. `Brief` and `RuleSet` typed models with units, provenance, and versioning.
2. A buildable-envelope service for setbacks, reservations, access, height,
   open-space, and other statutory constraints.
3. Pluggable candidate generators for footprints, cores, parking, and unit
   mixes. Start with geometric/optimization algorithms.
4. A deterministic evaluator that reports FSI, built-up area, efficiency,
   violations, and the exact rule/evidence behind every result.
5. Export adapters for DXF/GeoJSON/IFC and a scenario-comparison UI.

An LLM or agent may translate a client brief, explain alternatives, or choose
which deterministic tools to call. It must not calculate geometry, assert
compliance, or silently fill missing planning evidence. Any AI-derived input
should be shown for confirmation before entering the solver.
