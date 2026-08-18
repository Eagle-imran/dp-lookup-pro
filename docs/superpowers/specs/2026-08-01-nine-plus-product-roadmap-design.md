# `dp-lookup-pro` — Roadmap to a 9+ Product

**Date:** 2026-08-01  
**Status:** Strategic report for review  
**Approved sequence:** trusted expert engine → commercial web product → generative feasibility platform  
**Scope:** architecture, data correctness, CAD/report quality, testing, operations, productization, feasibility, site-plan generation, rendering, and pitch-deck generation

---

## Executive conclusion

`dp-lookup-pro` is already a good specialist tool. It is not an early prototype in the
usual sense: the CLI has been shaped by real upstream failures, real plot geometry,
rendered CAD inspection, and a growing regression corpus. Its strongest qualities are
speed, clarity of purpose, pragmatic failure handling, and unusually good written
memory of why apparently odd implementation choices exist.

The current scoping product is approximately **7.5/10 overall**. Its speed is already
around **9/10** for the constraints imposed by the MCGM services. The route to 9+ is
therefore not a rewrite and not a latency campaign. It is to make the hard-won
behaviour explicit, testable, versioned, and reusable before adding regulatory
calculation or generation.

The central recommendation is:

> Preserve the CLI as a stable interface, extract a canonical site model and
> deterministic calculation engine behind it, and make every later product—the web
> application, FSI engine, site-plan generator, renderer, and deck builder—a consumer
> of that same model.

The DXF should remain an important deliverable, but it should **not** become the
database or source of truth. DXF is optimized for exchange and drafting, not for
topology, provenance, regulatory reasoning, scenario lineage, or reliable round-trip
editing.

The most important work is not a new feature. It is eliminating the remaining ways a
report can look complete while being spatially or semantically incomplete.

---

## What was reviewed

This report is based on the current source, packaging, CI, test suite, generated
output corpus, and the complete documentation set, including:

- `README.md`, `START-HERE.md`, `SKILL.md`, `CONTRIBUTING.md`, and `LICENSE`;
- `docs/CHANGELOG.md`, `MEMORY.md`, `ROLLBACK.md`, `DXF-GUIDE.md`, and
  `FEATURES_PLANNED.md`;
- the HTML and JSON application-flow maps;
- the local spatial-cache specification;
- the approved PDF redesign specification;
- the current 2,567-line implementation and 1,366-line test module;
- CI across Python 3.9, 3.11, and 3.13;
- all 31 DXFs currently present in the output corpus.

At the time of review:

- **147 pytest cases pass** and Ruff is clean;
- the CLI usage and village-list smoke checks pass;
- all **31/31 existing DXFs pass** `tools/audit_dxf.py`;
- the implementation has one pre-existing uncommitted DXF label-collision change,
  which this report does not modify.

These are meaningful strengths. The recommendations below build on them.

---

## Current scorecard

Scores describe the product as it exists today for rapid Mumbai plot scoping. Future
features that do not yet exist are assessed separately as platform readiness, rather
than unfairly lowering the current CLI score.

| Aspect | Current | Why it scores here | What 9+ means |
| :--- | ---: | :--- | :--- |
| Problem selection and user value | **8.8** | Turns fragmented municipal GIS work into a usable bundle in seconds. Strong, specific professional value. | Repeated professional use demonstrates time saved, fewer missed constraints, and clear willingness to pay. |
| CLI and beginner experience | **8.2** | Plain-language summary, JSON mode, village help, one-command output, clean bundle. | Stable compatibility contract, structured exit codes, progress/job identity, and no ambiguous cache behaviour. |
| Speed and perceived latency | **9.0** | Split-wait design exposes the answer before slow imagery; upstream variability is understood and measured. | Published p50/p95 by stage, no regression beyond a fixed budget, and graceful behavior under MCGM throttling. |
| Reliability in known workflows | **8.1** | ArcGIS HTTP-200 errors, timeouts, incomplete files, CRZ mistakes, and multiple CAD regressions were handled thoughtfully. | No path to a confident answer from semantically empty or spatially partial data; complete provenance and explicit unknowns. |
| Geospatial correctness | **7.0** | Metric projection, real offsets, clipping, area disclosure, and neighbour conversion are strong. Centroid and multipart assumptions remain. | Topologically correct polygons, plot-wide intersections, representative points, calibrated adjacency, and geometry validity gates. |
| CAD usefulness and readability | **8.3** | True offsets, road geometry, lineweights, text measurement, 12 purposeful layers, and corpus auditing are unusually mature. | Automated release-gated visual audit, topology support, frontage confidence, scale/CRS metadata, and architect validation. |
| PDF/map deliverables | **6.7** | Useful two-page bundle, but the documented redesign identifies broken emoji, weak hierarchy, whitespace, and no PDF tests. | Decision-first report, accessible typography, tested fallback states, visual regression checks, and branded templates. |
| Automated testing and QA | **7.7** | 147 offline tests cover many hard geometric and rendering regressions; CI spans supported Python versions. | Full mocked orchestration, schema contracts, property/topology tests, artifact rendering gates, live canaries, and a curated golden corpus. |
| Architecture and maintainability | **5.6** | Most product responsibilities live in one module; the main workflow alone is roughly 590 lines. | Clear domain/application/adapter boundaries, typed canonical models, stable compatibility facade, and isolated renderers. |
| Documentation quality | **7.8** | The changelog and memory preserve exceptional reasoning and failure history. | One generated source of operational truth; no drift in counts, versions, TTLs, layers, commands, or workflow diagrams. |
| Observability and supportability | **4.8** | User warnings are useful, but there is no durable request trace, endpoint metric set, or release telemetry. | Per-run trace manifest, stage timings, result counts, source versions, cache decisions, artifact checksums, and privacy-safe diagnostics. |
| Security and data governance | **6.2** | Input sanitization and narrow outbound service use are good. Commercial data rights and multi-user controls are unresolved. | Threat model, dependency scanning, signed releases, tenant isolation, retention policy, and confirmed data/basemap rights. |
| Commercial web readiness | **4.5** | Strong engine and outputs, but no API boundary, jobs, accounts, audit trail, project model, or operational service design. | Production API, job queue, object storage, auth/RBAC, billing boundary, support tooling, backups, and service objectives. |
| Feasibility-engine readiness | **5.4** | Useful parcel, road, constraint, and area inputs exist; governing area and legal rule modelling remain unresolved. | Versioned deterministic rule engine with citations, assumptions, blockers, scenario lineage, and professional validation. |
| Generative planning/render/deck readiness | **3.0** | Ambition is clear, but there is not yet a canonical 2D/3D scenario model or validator. | Constrained generation, Pareto-ranked options, machine-verifiable compliance, reproducible rendering, and evidence-linked decks. |

### Overall assessment

- **Current rapid-scoping tool:** approximately **7.5/10**.
- **Current foundation for the full platform:** approximately **6/10**.
- **Potential:** comfortably **9+**, if correctness and canonical modelling precede
  feature breadth.

---

## The assets that must be protected

These are not incidental implementation details. They are product invariants created
through costly iteration and should become named regression contracts.

1. **“Confidently incomplete” is the worst failure mode.** A missing planning response
   must never silently become `Unknown`, `NO`, `None`, and ultimately `CLEAR`.
2. **ArcGIS can return an error inside HTTP 200.** Every endpoint response must pass
   protocol and semantic validation, not merely status-code validation.
3. **Planning failure is fatal; optional enrichment failure is visible.** Zoning,
   reservation, modification, CRZ, and other governing data require an explicit
   answer or explicit failure. Imagery and some enrichment can degrade with warnings.
4. **Road detection is not a normal feature query.** Layers 193/194 required identify
   calls, and corner/edge probes fixed real regressions. Existing probes cannot be
   removed casually.
5. **The split-wait pipeline is a user-experience feature.** The fast planning answer
   should remain available without waiting for images or the PDF.
6. **Geometry must be measured in the correct coordinate system.** Web Mercator,
   WGS84, and local metric coordinates have distinct roles and must never be inferred
   from a naked coordinate list.
7. **Setbacks are true parallel offsets and are only indicative.** They must be exact
   at the stated distance, omitted if geometrically impossible, and never presented
   as DCPR compliance.
8. **Rendered text must be measured.** DXF entity insertion points do not prove
   readability. Text extents, collision handling, visual rendering, and corpus-level
   checks are required.
9. **Road geometry needs segment-aware clipping and proximity ranking.** Sparse paths
   can cross the sheet without placing a vertex in it; response order is not
   relevance order.
10. **MCGM area and drawn area are different facts.** Both must remain visible, with
    source labels and discrepancy disclosure. Property Card/site-survey area remains
    a required external input for serious feasibility.
11. **Cache hits must not promise missing artifacts.** Bundle integrity verification
    and incomplete-result non-caching remain mandatory.
12. **Exact cadastral identity matters.** `16/738` and `16-738` are different plots;
    paths, cache keys, manifests, and UI identity must preserve that distinction.
13. **The simple installation is part of the product.** Native dependencies or heavy
    infrastructure should not be pushed into the local expert CLI without a clear
    payoff and fallback.

Every extraction or refactor should begin with characterization tests for these
contracts and end with the same CLI/API/output behavior unless a versioned migration
is explicitly intended.

---

## Three possible evolution strategies

### A. Platform rewrite first

Build a web service, new database, and new UI, then recreate the CLI behavior in the
new stack.

**Advantages:** clean-looking architecture quickly; easier to hire around conventional
web boundaries.  
**Risks:** the undocumented edge behavior is rediscovered through production mistakes;
the working latency model and CAD details are easy to lose; feature work pauses while
parity is rebuilt.  
**Verdict:** not recommended.

### B. Contract-first modular evolution — recommended

Freeze the current public behavior with characterization and corpus tests. Introduce
a canonical model inside the existing process. Extract source clients, geometry,
interpretation, storage, and renderers behind stable interfaces one seam at a time.
Keep `lookup_plot_pro` and the CLI as compatibility facades. Build the API and web
application against the extracted application service.

**Advantages:** preserves proven behavior; risks are bounded; every phase delivers
value; the same engine serves CLI and web; future FSI and generation get clean inputs.  
**Risks:** requires discipline to avoid “temporary” cross-module shortcuts; briefly
creates old and new shapes during migration.  
**Verdict:** best fit for the project and the approved sequence.

### C. Feature-first growth inside the current module

Add FSI, HTML reports, heritage, web endpoints, and generation directly around the
existing result dictionary.

**Advantages:** fastest demos and shortest path to more checkboxes.  
**Risks:** every feature increases the blast radius of changes; ambiguous strings such
as `None`, `Unknown`, and `YES (...)` become de facto APIs; legal rules become mixed
with rendering and network code; testing becomes increasingly indirect.  
**Verdict:** suitable only for disposable experiments, not a 9+ commercial product.

---

## Target architecture

The target should be a modular monolith first, not a fleet of services. A single
deployable application with strong internal seams is enough for the expert CLI and
the first web product. Split services only when operational evidence demands it.

```text
MCGM / Esri / user documents / survey inputs
                    │
                    ▼
          Source adapters + validators
                    │
                    ▼
       Canonical Site Model + provenance
          │              │              │
          ▼              ▼              ▼
  Spatial analysis   Rule engine   Scenario generator
          │              │              │
          └──────────────┴──────────────┘
                         │
                         ▼
              Validated scenario graph
          │          │          │          │
          ▼          ▼          ▼          ▼
        CLI/API      DXF/GIS     3D/render   PDF/deck
```

### 1. Canonical Site Model

This becomes the internal source of truth. It should be typed and schema-versioned,
not a loosely interpreted renderer dictionary.

At minimum it should hold:

- exact parcel identity and a collision-free canonical ID;
- polygon/multipolygon topology, explicit CRS, and local metric transform;
- official area, measured boundary area, supplied survey/Property Card area, and the
  selected governing area—each as a separate sourced value;
- zone, reservations, designations, modifications, CRZ/metro intersections, roads,
  neighbours, and other constraints;
- source endpoint, layer ID, retrieval time, source feature/object ID, and raw evidence
  reference for every derived fact;
- `known`, `not_present`, `not_applicable`, `failed`, and `not_checked` as distinct
  states rather than overloaded strings;
- confidence/method labels such as `polygon_intersection`, `representative_point`,
  `probe`, `spatial_cache`, `user_confirmed`, or `derived`;
- warnings, blockers, and freshness policy;
- immutable scenario lineage: input version, rule-set version, assumptions, and
  generated artifacts.

Persist it as JSON for portability plus SQLite/PostgreSQL for indexed operation.
GeoJSON may represent exchange geometry, but topology-aware internal geometry should
use a format such as WKB. DXF is generated from this model.

### 2. Source adapters

The MCGM and Esri clients should own endpoint details, payload construction, response
validation, retries, rate limits, and source-specific parsing. The application layer
should ask for `Parcel`, `PlanningEvidence`, `RoadEvidence`, or `Imagery`, not know
ArcGIS layer attribute spellings.

Each response needs three validation levels:

1. transport: request completed and content type/status are plausible;
2. protocol: valid ArcGIS JSON/image, no embedded `error` body;
3. semantics: required layers and attributes are present and spatial coverage is
   adequate for the claim being made.

For example, a planning identify response with `{"results": []}` is valid JSON but
is not a valid basis for a clear report. At least the expected zoning evidence must be
present, and optional-layer absence must be distinguished from total identify failure.

### 3. Spatial analysis engine

Use Shapely or equivalent deterministic geometry for:

- geometry repair/validation and ring topology;
- an interior representative point rather than mean-of-vertices “centroid”;
- plot-wide intersection with CRZ, metro, reservations, and other polygonal
  constraints wherever the source service permits geometry queries;
- boundary overlap and frontage scoring against road geometry;
- accurate adjacency with a calibrated, disclosed tolerance;
- setbacks, buffers, buildable envelopes, coverage, areas, and scenario validation.

Point sampling may remain as a documented fallback when an MCGM layer cannot answer a
polygon query, but it must carry an approximation method and cannot silently support a
plot-wide `NO` claim.

### 4. Regulatory rule engine

FSI, BUA, height, setbacks, parking, and incentives must be deterministic. LLMs should
not decide legal arithmetic.

Every rule should have:

- rule-set and effective-date version;
- exact regulation/table/clause citation;
- typed inputs and units;
- preconditions and mutually exclusive branches;
- calculation trace showing each intermediate value;
- missing-input blockers;
- professional review fixtures and expected results;
- a statement of whether the output is screening, indicative feasibility, or
  professionally verified.

Start with a deliberately narrow set of common development scenarios. A smaller rule
engine that knows when it cannot answer is more valuable than a broad one that silently
chooses the wrong regulation.

### 5. Scenario and generation engine

The generator should operate as constrained optimization, not prompt-to-plan.

1. Normalize the development brief and required inputs.
2. Build hard constraints from site geometry and the selected rule scenario.
3. Generate candidate footprints/massing/product mixes.
4. Validate every candidate against hard constraints.
5. Score valid candidates across saleable area, FSI consumption, access, efficiency,
   daylight/open-space proxies, cost, and user preferences.
6. Return a Pareto set with explicit trade-offs—not one mysterious “best” answer.

LLMs are useful for extracting a brief from documents, identifying missing inputs,
explaining scenarios, naming options, and drafting narrative. They should never be the
only checker of geometry, arithmetic, or regulatory eligibility.

### 6. Artifact pipeline

Every artifact should be a renderer of the same immutable scenario:

- DXF/GIS for professional downstream work;
- 2D diagrams including site plan, FSI-consumption map, access, open space, and area
  schedule;
- a neutral 3D massing model such as glTF, with IFC as a later professional exchange
  target if the product genuinely needs BIM semantics;
- reproducible cameras, materials, sun settings, and render briefs;
- presentation renders through a replaceable rendering backend;
- a deck assembled from structured facts, charts, images, assumptions, citations, and
  scenario comparisons.

The deck must never invent a number that is not present in the scenario model. Every
material claim should be traceable to a source, rule calculation, or explicit user
assumption.

---

## Critical correctness work before expansion

These items deserve priority over new feature breadth.

### P0 — prevent confident wrong answers

1. **Reject semantically empty planning responses.** `usable_json` correctly
   distinguishes parse/ArcGIS failure, but `{"results": []}` still flows into default
   `Unknown`/`None`/`NO` values and can produce a clear-looking report. Require minimum
   evidence and add full orchestration tests.
2. **Eliminate exact-identity path collisions.** The current folder normalization maps
   slash and hyphen to the same path even though the documentation correctly says
   `16/738` and `16-738` are different parcels. Introduce a reversible or hash-backed
   canonical bundle ID while preserving common existing paths.
3. **Replace vertex-mean point selection.** The current point is an average of ring
   vertices, not a guaranteed interior point. It can fall outside a concave parcel and
   invalidate point-based identification.
4. **Use plot-wide spatial checks for polygon constraints.** A centroid-only CRZ or
   metro check can miss a partial intersection. Query/intersect returned geometries
   where possible; use multiple representative samples only as an explicitly labelled
   fallback.
5. **Make unknown distinct from negative.** `NO`, `None`, `Unknown`, missing key,
   request failure, and layer not checked must not collapse into the same rendering or
   status logic.

### P1 — close known geometry and persistence gaps

1. Correctly model multipart parcels and holes across DXF, GeoJSON, KML, adjacency,
   area, and setbacks. The current KML path exports only the first ring, while other
   renderers accept rings without representing hole semantics consistently.
2. Rank and clip roads using segment-to-polygon distance so a sparse crossing road is
   not discarded before clipping.
3. Validate satellite payloads as decodable images, not merely non-empty HTTP 200
   bodies; record tile provider/time and placeholder status.
4. Make JSON cache and Excel-register writes process-safe and atomic. The planned
   SQLite/WAL work is appropriate for cache state; the Excel register should be
   generated from an append-only database or guarded by an explicit lock.
5. Remove or pin through the 139 current `ezdxf` deprecation warnings before an
   upstream release converts them into failures.
6. Implement the already-approved PDF redesign and its test plan rather than adding a
   second report format first.

### P2 — reconcile cache semantics

The documentation says both “geometry is cached, planning is always live” and that the
existing 30-day bundle cache carrying planning status remains unchanged. Both cannot be
the default meaning of a fresh “lookup.”

Recommended semantics:

- **Geometry cache:** long-lived (for example 180 days), bypassed by `--no-cache`.
- **Tile/image cache:** provider-policy-aware, separately aged.
- **Planning lookup:** live by default, or a deliberately short operational TTL with
  an explicit freshness stamp.
- **Generated report:** immutable “as-of” snapshot that can be reopened exactly.
- **Reuse old report:** explicit command/flag, not indistinguishable from a fresh
  regulatory lookup.

This preserves fast geometry and exact artifact reuse while making freshness honest.
The split-wait behavior should remain.

---

## Quality system required for 9+

### 1. Test pyramid tailored to this product

**Pure unit tests** — continue the current strength in geometry, parsing, status
derivation, rendering helpers, and path handling.

**Full mocked orchestration tests** — simulate the entire lookup for:

- complete clear, modified, and reserved plots;
- HTTP 200 ArcGIS error;
- timeout and partial road/neighbour failures;
- empty planning results;
- missing required zoning evidence;
- corrupt imagery;
- multipart/hole geometry;
- cache hit, stale cache, missing artifact, and concurrent writers;
- callback snapshot followed by final result.

These tests should assert request count/types only where they are genuine contracts;
otherwise assert outcomes and required source calls to avoid freezing implementation
accidents.

**Schema/contract tests** — version and validate the canonical model, public result
JSON, bundle manifest, CLI exit behavior, and compatibility facade.

**Golden spatial corpus** — promote the existing output set into curated fixtures. It
should include at least:

- coastal and inland controls;
- clear, modified, designated, and reserved statuses;
- tiny, large, narrow, concave, multipart, and hole-bearing parcels;
- null approved area and large approved/measured discrepancy;
- long road labels, sparse road geometry, and no-road cases;
- slash/hyphen identities and suffix CTS numbers;
- partial CRZ/metro intersection;
- known adjoining sets in multiple villages.

For every fixture, retain raw source responses or legally safe normalized evidence,
expected structured facts, expected geometry invariants, and artifact assertions.

**Visual/artifact gates** — in CI or a release workflow:

- open every DXF with `ezdxf`, run `audit_dxf.py`, and rasterize representative files;
- render PDFs and inspect page count, extracted text, replacement glyphs, clipping,
  and golden image differences;
- decode all PNGs and verify expected dimensions/content markers;
- validate GeoJSON and KML schemas/topology;
- verify the bundle manifest and checksums.

**Live canaries** — a scheduled, rate-limited job against a small positive/negative set,
not a merge-blocking test. It should detect source schema/layer changes and notify the
maintainer before users discover them.

### 2. Observability

Create a per-run trace ID and machine-readable manifest containing:

- application, schema, and rule-set versions;
- exact identity and query parameters;
- source endpoint/layer IDs and retrieval timestamps;
- stage and endpoint durations;
- response result counts and semantic validation outcomes;
- retry/rate-limit decisions;
- cache hit/miss reason and age by cache type;
- derived-fact methods and warnings;
- artifact paths, sizes, MIME types, checksums, and generation status.

Human output can remain concise. `--diagnostics` or a trace file should expose the
detail needed for support without dumping credentials or sensitive uploaded documents.

### 3. Release gates

A release candidate should not ship unless:

- unit, orchestration, schema, and artifact tests pass on supported Python versions;
- the golden corpus has zero unexplained fact or geometry differences;
- representative DXFs and PDFs pass rendered visual review;
- no new deprecations or unclassified warnings are introduced;
- p50/p95 fast-answer and complete-bundle latency stay within the agreed budget;
- documentation contract checks pass;
- migration and rollback paths are exercised;
- the release manifest and changelog identify data/rule/schema changes separately.

---

## Documentation as an executable product surface

The documentation is thoughtful, but currently drifts because the same facts are
repeated manually. Examples found during this review include:

- README says 30 days and 24 hours in the same paragraph;
- current workflow can issue up to 31 calls, while several docs say 25;
- road probes are now up to 15, while the flow map and memory say 9;
- the flow map says 11 DXF layers, while the current drawing defines 12;
- contributing guidance says 70 tests, while the current suite has 147;
- the flow map remains labelled v3.10.0 and its source line references are stale;
- `DXF-GUIDE.md` still says it was generated by v3.10.1;
- the README's fallback `pip` command omits the required `shapely` dependency;
- the README's bundle tree names `_sat.png`, while the implementation writes
  `_satellite.png`;
- `START-HERE.md` describes a six-file plot folder but counts the shared Excel register
  as one of the six and omits the GeoJSON that is actually inside each bundle;
- the spatial-cache roadmap first says it replaces the JSON cache, then correctly
  specifies that it adds SQLite beside the existing bundle cache;
- planning-always-live conflicts with 30-day cached planning bundles.

Recommended model:

1. Put stable product concepts and rationale in hand-written documents.
2. Generate version, layer list, CLI options, schema examples, request-plan summary,
   test count, and output list from code or a checked manifest.
3. Add a documentation test that fails on contradictory TTLs, stale version markers,
   missing dependencies, broken links, and schema examples that do not validate.
4. Replace fragile source line numbers in the flow map with stable component/function
   identifiers.
5. Keep `MEMORY.md` as an architectural decision record, but split major decisions
   into dated ADRs once multiple contributors or a commercial service exist.

The documentation should tell different audiences different truths without duplicating
operational constants:

- `START-HERE`: non-technical user journey and limitations;
- `README`: supported developer interface and current capabilities;
- architect guide: CAD meaning, confidence, and required checks;
- operations runbook: canaries, source outages, rollback, and incident response;
- rule handbook: regulatory sources, versions, tests, and interpretation decisions;
- API/schema reference: generated from the canonical model.

---

## Product horizons

### Horizon 1 — trusted expert engine

The product promise is: “Given exact parcel identity and current public source data,
produce a fast, traceable, architect-usable screening package, and clearly refuse or
qualify anything it cannot establish.”

#### Deliverables

- resolve P0 correctness issues;
- compatibility-preserving modular extraction;
- canonical Site Model v1 and bundle manifest;
- spatial cache with corrected freshness semantics;
- complete mocked orchestration suite;
- curated golden corpus and release artifact audit;
- approved PDF redesign;
- structured diagnostics and source provenance;
- limited batch/project mode without unsafe concurrent Excel writes;
- an input checklist for governing area, survey, title/PRC, intended use, tenure,
  redevelopment route, road verification, and other feasibility prerequisites.

#### 9+ gate for Horizon 1

- zero known paths from missing evidence to a negative/clear claim;
- 100% of released bundles carry schema version, source timestamps, completeness,
  methods, and checksums;
- all golden fixtures pass structured and rendered artifact checks;
- default planning answer is current according to a documented freshness contract;
- p50 fast answer remains around one second where the upstream service permits, with
  p95 and timeout behavior published honestly;
- an architect can identify what is authoritative, derived, approximate, stale, or
  missing without reading source code.

### Horizon 2 — commercial multi-user web product

The web product should call the same application service as the CLI. Do not fork the
calculation logic into a second implementation.

#### Product capabilities

- organizations, users, projects, parcels, and scenarios;
- role-based access and tenant isolation;
- server-side job queue with progress from fast answer through document completion;
- immutable run history and compare/diff;
- object storage for artifacts and database storage for models/audit records;
- upload flow for survey, PRC, DP remark, title/brief, and professional confirmations;
- input-completeness dashboard and explicit blockers;
- review/approval states and professional sign-off fields;
- share links with expiry and download/audit history;
- support diagnostics tied to trace ID;
- usage/billing boundary without coupling billing to calculation code.

#### Operational requirements

- service-level objectives for availability and job completion;
- idempotent jobs and safe retry behavior;
- backups, restore drills, retention/deletion controls;
- dependency and container scanning, secret management, signed builds;
- source-service rate limiting and circuit breaking;
- privacy policy, terms, support process, and incident runbook;
- explicit treatment of MCGM data, Esri imagery, uploaded documents, and generated
  render rights.

#### 9+ gate for Horizon 2

- the web and CLI produce the same model and equivalent artifacts for identical input;
- every job is traceable and safely retryable;
- tenant data cannot cross boundaries in tests or operations;
- users understand data freshness and review state at every decision point;
- recovery, support, and source-outage behavior are exercised rather than theoretical.

### Horizon 3 — feasibility, site-plan, render, and pitch-deck platform

Build this as successive confidence layers.

#### Layer A — feasibility engine

- user confirms governing area and scenario route;
- deterministic FSI/BUA and constraint calculations;
- FSI consumption waterfall/map;
- required vs available inputs and blockers;
- side-by-side development scenarios with cited assumptions;
- architect-reviewed fixtures for every supported rule path.

#### Layer B — parametric site planning

- normalized development brief and product-mix targets;
- buildable envelope and access/frontage model;
- hard-constraint validator;
- candidate layout/massing generator;
- parking/core/open-space/fire-access modules as the selected scenario requires;
- Pareto ranking and user-adjustable weights;
- DXF/GeoJSON/3D exports generated from each scenario model.

#### Layer C — visualization

- neutral massing views first;
- reproducible camera/sun/context settings;
- design-language and material controls kept separate from regulatory geometry;
- rendering backend interface so Blender, real-time, or external render services can
  change without changing the scenario model;
- visible distinction between conceptual imagery and approved architectural design.

#### Layer D — pitch deck

- controlled templates with optional firm/developer branding;
- auto-selected evidence, maps, schedules, comparisons, and renders;
- scenario-specific narrative generated from structured facts;
- citations, assumptions, exclusions, and snapshot dates on every relevant slide;
- deterministic charts and tables; LLM-generated prose only where narrative helps;
- final validation that all deck numbers equal the scenario model.

#### 9+ gate for Horizon 3

- every generated option passes machine-verifiable hard constraints for the rule scope
  it claims to support;
- no deck or render can detach from its input/rule/scenario versions;
- experts can alter assumptions and reproduce the result;
- options expose trade-offs and uncertainty instead of presenting one opaque answer;
- conceptual outputs are unmistakably labelled and reviewable by an architect.

---

## Phased execution roadmap

Durations are indicative for a focused small team and should be converted into a
delivery plan only after scope and staffing are fixed.

| Phase | Indicative duration | Outcome | Do not combine with |
| :--- | :--- | :--- | :--- |
| **0. Safety and contracts** | 1–2 weeks | Characterization tests, P0 fixes, schema/freshness decision, canonical fixture manifest. | New regulatory features. |
| **1. Modular core** | 3–6 weeks | Typed Site Model, source adapters, geometry service, renderer interfaces, compatibility facade. | A web rewrite. |
| **2. Quality and deliverables** | 4–8 weeks | Full orchestration tests, golden corpus gates, diagnostics, PDF redesign, deprecation cleanup, atomic persistence. | Broad rule automation. |
| **3. Expert feasibility v1** | 6–10 weeks | Narrow, versioned rule engine; governing-area workflow; calculation trace; scenario comparison. | Unsupported DCPR branches presented as complete. |
| **4. Commercial web v1** | 6–10 weeks | Projects, jobs, auth/RBAC, artifacts, run history, review state, support trace. | Separate calculation implementation. |
| **5. Parametric scenarios** | 8–16+ weeks | Constraint model, candidate generation, validation, scoring, 2D/3D scenario outputs. | Prompt-only plan generation. |
| **6. Render and deck pipeline** | 6–12 weeks after stable scenarios | Reproducible visuals and evidence-linked pitch decks. | Numbers or geometry generated only in prose. |

### Recommended first 30 days

1. Create an explicit public compatibility contract for CLI arguments, Python call,
   callback timing, JSON schema, paths, warnings, and artifact list.
2. Add failing regression tests for empty planning results, slash/hyphen bundle
   identity, concave representative points, and partial polygon intersection.
3. Decide cache semantics and document “fresh lookup” versus “reopen snapshot.”
4. Define Site Model v1 and a bundle `manifest.json` before moving functions.
5. Add one full mocked end-to-end lookup test, then expand to the failure matrix.
6. Turn the 31-DXF corpus into a named release corpus with expected outcomes and
   immutable source snapshots where permitted.
7. Implement and test the approved PDF redesign.
8. Extract in thin seams while keeping `cts_dp_lookup_pro.lookup_plot_pro` working.
9. Add generated documentation checks and update stale counts/version references.
10. Establish a small architect review group and a signed-off fixture process before
    implementing FSI.

---

## Decisions required before FSI automation

The existing documents are correct that wrong FSI is worse than no FSI. Resolve these
before implementation:

1. Which area governs each supported scenario: MCGM record, PRC, survey, net plot after
   deductions, or another rule-derived area?
2. Which DCPR version, amendments, circulars, and effective dates form each rule set?
3. Which development routes are supported first and which are explicitly excluded?
4. How are road width and access confirmed when public GIS and survey/title evidence
   disagree?
5. Which reservations, CRZ/heritage/aviation/rail/infrastructure constraints block an
   automated answer rather than merely warn?
6. What professional review and sign-off changes a scenario from “screening” to
   “reviewed feasibility”?
7. How are premiums, TDR availability, fungible components, rehab/sale components,
   deductions, and incentive caps represented without double-counting?
8. What uncertainty ranges should be shown for market/product inputs and unresolved
   regulation?

The initial rule engine should be chosen by frequency and clarity, not ambition.

---

## Legal, licensing, and professional-risk work

Before commercial launch or bulk spatial distribution:

- confirm rights and terms for querying, caching, redistributing, and commercially
  presenting MCGM parcel/planning data;
- confirm Esri imagery caching, derivative, attribution, and client-delivery terms;
- track the source and permitted use of DCPR text, tables, notices, fonts, templates,
  maps, textures, and generated imagery;
- separate “public source screening,” “computed feasibility,” “professional review,”
  and “official approval” in the data model and UI—not only in footer disclaimers;
- obtain professional advice on liability language and expected duty of care;
- define retention and deletion for uploaded title/property documents;
- keep a complete audit trail of user inputs, rule versions, manual overrides, and
  approvals.

Disclaimers remain necessary, but a 9+ product also makes misuse difficult through
workflow state, provenance, blockers, and visible confidence.

---

## What not to do

- Do not rewrite the working CLI before its behavior is captured.
- Do not use the DXF as the only source for later automation.
- Do not let an LLM decide FSI, setbacks, geometry validity, or compliance.
- Do not treat a successful HTTP response or empty result list as sufficient evidence.
- Do not add more point probes where polygon intersection is available.
- Do not make cached planning status look current.
- Do not start with every DCPR redevelopment route.
- Do not optimize sub-second local work while upstream semantic reliability remains
  unresolved.
- Do not generate polished renders or decks before the scenario can be reproduced and
  validated.
- Do not split into microservices merely to look “enterprise.”

---

## Final 9+ scorecard

The product can reasonably call itself 9+ when all of the following are true:

| Dimension | 9+ evidence |
| :--- | :--- |
| Correctness | No known silent-negative path; plot-wide spatial checks; explicit unknown states; expert-validated rule fixtures. |
| Reliability | Safe degradation, atomic/idempotent operations, source canaries, immutable snapshots, and tested recovery. |
| Performance | Fast-answer behavior preserved; p50/p95 by stage published; rate limits handled; no unexplained regressions. |
| Professional usefulness | Architects can trace, edit, verify, and reconcile every material input and output. |
| Architecture | One canonical model and calculation engine power CLI, web, CAD, feasibility, rendering, and decks. |
| QA | Mocked end-to-end tests, golden spatial corpus, rendered artifact gates, schema contracts, and live canaries. |
| Transparency | Every fact has source, method, age, confidence/state, and calculation lineage. |
| Product UX | Missing inputs become actionable blockers; projects/scenarios are easy to compare; outputs are clearly labelled. |
| Operations | Traceable jobs, support diagnostics, tenant isolation, backups, incident handling, and service objectives. |
| Governance | Data rights, professional-risk boundaries, rule versions, user overrides, and approvals are documented and auditable. |

The project is closest to 9+ in speed, problem value, and accumulated practical
knowledge. It is furthest away in internal architecture, end-to-end verification,
observability, and the canonical model required for future generation. That ordering is
useful: the hardest domain lessons have already been learned. The next job is to encode
them so the product can grow without having to learn them again.
