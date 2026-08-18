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
        +--> clients: payloads / planning queries / transport / caches
        |
        +--> optional planning_evidence registry/models
                     ^
                     |
              clients.planning_evidence_queries
```

- `core` contains constants, geometry/topology, planning classification, and
  typed result models. It must not import clients, exporters, or renderers.
- `clients` owns external protocols: ArcGIS request/response adaptation,
  verified HTTP transport, and the persistent cache.
- `planning_evidence` owns immutable due-diligence models and the audited,
  dependency-free layer registry. Its ArcGIS adapter remains in `clients`, so
  source transport cannot leak into the evidence/domain contracts.
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
| `planning_evidence/models.py` | Immutable evidence modes, findings, layer outcomes, and report |
| `planning_evidence/registry.py` | Audited layer schemas, authority classes, duplicate and applicability policy |

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

## ArcGIS ingestion contract

The current lookup depends on these MCGM Development Plan layers:

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
changes separately from deterministic pull-request CI.

Each run records a unique ID and stage timings in `metadata.diagnostics`.
`DP_LOOKUP_LOG_JSON=1` mirrors stage-completion events as JSON on stderr for
automation and incident diagnosis without coupling the library to a monitoring
vendor.

The optional planning-evidence profile runs only after the validated Layer 13
parcel is available and never re-queries it. `basic` preserves the historical
request/cache contract; `shadow` and `standard` query the curated decision and
CZMP set; `full` adds wider screening sources and activates TPS, SPA, and
Gorai-Manori families only after a detector polygon intersects. Non-basic cache
keys include the evidence profile and registry version, and incomplete optional
evidence is never cached. Findings are nested under
`metadata.evidence.planning_due_diligence`, leaving the public top-level result
shape and status calculation intact.

`--no-cache` controls cache reads, not persistence: it forces a fresh source
request and a complete result replaces the relevant mode-specific cache entry.
This makes the normal workflow fast while providing an explicit refresh path
for client issues, submissions, transactions, and upstream-change validation.

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
