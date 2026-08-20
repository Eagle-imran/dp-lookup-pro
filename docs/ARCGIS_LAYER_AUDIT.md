# MCGM ArcGIS layer audit

**Status:** engineering record / pre-rollout audit  
**Service audited:** [MCGM Development Plan 2034 MapServer](https://agsmaps.mcgm.gov.in/server/rest/services/Development_Plan_2034/MapServer)  
**Audit window:** live checks recorded in this project on 28 July–18 August 2026 (the service is external and can change after that date)

This document is deliberately conservative. `Observed` means that the behaviour was seen in the MCGM REST response or in a reproducible project run. `Inference` means an engineering interpretation of that response. `Legal verification` means a conclusion that must be checked against the current notification, sanctioned plan, property/DP record, or competent authority; GIS overlap alone is not that conclusion.

## Scope and method

The audit asked whether the MCGM service can support a planning-evidence module without changing the existing parcel lookup. It covered:

1. service and layer metadata (`?f=pjson`);
2. geometry type, fields, aliases, visibility/scale and query behaviour;
3. exact parcel-wide polygon intersections, rather than centroid-only checks;
4. agreement and disagreement between duplicate-looking layers;
5. a ten-parcel CTS corpus containing inland, coastal, modified, large and partial-overlap controls;
6. response size, throttling and failure behaviour; and
7. the evidence/authority boundary needed before the results can be used in a feasibility workflow.

The primary REST operations were `MapServer/{layer_id}?f=pjson` and `MapServer/{layer_id}/query` with a bounded parcel envelope, `returnGeometry=true`, selected `outFields`, and `f=json`. Raw responses, request parameters, timestamps, service URL and parser version should be retained with every future audit run. The service root is the canonical inventory; a layer number must never be treated as a permanent meaning without re-reading its metadata.

## Current production layer set

These are the layers currently used by the lookup engine. The links point to the official MCGM REST metadata pages.

| Layer | Current role | Geometry/evidence note |
|---:|---|---|
| [13](https://agsmaps.mcgm.gov.in/server/rest/services/Development_Plan_2034/MapServer/13) | CTS/cadastral parcel identity and geometry | Required parcel source; carries identity and area fields, not the complete planning answer. |
| [0](https://agsmaps.mcgm.gov.in/server/rest/services/Development_Plan_2034/MapServer/0) | DP zoning | Required planning evidence; the run fails closed when usable zoning evidence is unavailable. |
| [46](https://agsmaps.mcgm.gov.in/server/rest/services/Development_Plan_2034/MapServer/46) | reservations | Polygon intersection and reservation attributes. |
| [47](https://agsmaps.mcgm.gov.in/server/rest/services/Development_Plan_2034/MapServer/47) | designations | Polygon intersection and designation attributes. |
| [192](https://agsmaps.mcgm.gov.in/server/rest/services/Development_Plan_2034/MapServer/192) | DP modifications | Historical/proposed/sanctioned modification evidence; status and final code need careful parsing. |
| [14](https://agsmaps.mcgm.gov.in/server/rest/services/Development_Plan_2034/MapServer/14), [1264](https://agsmaps.mcgm.gov.in/server/rest/services/Development_Plan_2034/MapServer/1264), [1548](https://agsmaps.mcgm.gov.in/server/rest/services/Development_Plan_2034/MapServer/1548) | CRZ zone polygons | Current CRZ candidate set; tier is read from variant category fields. |
| [1550](https://agsmaps.mcgm.gov.in/server/rest/services/Development_Plan_2034/MapServer/1550) | Metro influence/buffer | Planning warning; do not infer a statutory setback from the buffer alone. |
| [193](https://agsmaps.mcgm.gov.in/server/rest/services/Development_Plan_2034/MapServer/193), [194](https://agsmaps.mcgm.gov.in/server/rest/services/Development_Plan_2034/MapServer/194), [44](https://agsmaps.mcgm.gov.in/server/rest/services/Development_Plan_2034/MapServer/44), [45](https://agsmaps.mcgm.gov.in/server/rest/services/Development_Plan_2034/MapServer/45), [2224](https://agsmaps.mcgm.gov.in/server/rest/services/Development_Plan_2034/MapServer/2224) | road/access probes | Mixed road geometry/labels; selected by proximity and clipped by segment. |

`Layer 13` is the identity anchor, not a legal title or Property Card substitute. The application's area comparison already records that MCGM's tabular area and digitised polygon can differ materially (for example, AMBIVALI 807: 6.10%). No FSI or yield calculation should silently choose one figure.

## Ten-CTS live layer-audit corpus

The additional-layer audit used these exact Layer 13 records. A future audit should rerun them without cache and save the raw query manifest. They are a deliberately varied engineering sample, not legal determinations or a statistically representative sample.

| Case | Layer 13 OBJECTID | Why it is in the corpus |
|---|---:|---|
| KOLEKALYAN 5806 | 55845 | suburban control |
| COLABA 1/600 | 15563 | dense multi-overlap coastal/heritage/port control |
| MULUND-E 637 | 90785 | refused/reinstated EP decision control |
| MALAD-NORTH 266 | 67422 | western-suburb control |
| WADHAVALI 403 | 131391 | eastern-suburb control |
| BHULESHWAR 1435 | 35212 | dense city control |
| MALABAR HILL 1/6 | 32718 | complete CRZ-II overlap control |
| NAHUR 569/22 | 88504 | slash-preserving CTS control |
| GUNDAVALI 367 | 76001 | urban smoke control |
| VILE PARLE 1449 | 98178 | 100% mapped Gaothan control |

The established product regression corpus additionally includes WORLI 733/886/947, BANDRA-A 409, BYCULLA 1605, TARDEO 264, MOHILI 732, AMBIVALI 807, MULUND-W 22 and DADAR-NAIGAON 98. Keep the live layer-audit corpus and the product regression corpus distinct.

## What the official service does—and does not—provide

**Observed:** MCGM exposes a public ArcGIS REST MapServer with layer metadata and feature queries. The service contains a mixture of polygon, line and road layers, and attributes are not uniform across related layers. Some fields are exposed under aliases or variant casing. The service's response is an operational GIS record, not a signed planning certificate.

**Observed:** the service can return an HTTP-success JSON object that is semantically empty, contains an ArcGIS `error`, or returns no intersecting features. Empty results therefore cannot be converted to `NO` without a successful query audit and a geometry/type check.

**Observed:** request latency varies and broad query batches can slow substantially. Individual positive-control requests were commonly about 60–250 ms; heavier layers such as heritage, water buffers and CZMP were approximately 1–1.7 seconds in the audited run. A bounded 46-layer diagnostic batch varied from about 8.8 to 32 seconds. These measurements support curated and conditional queries, not an all-layers default.

**Inference:** the service is excellent source evidence for a screening workflow, but it cannot by itself establish that a reservation is deleted, a modification is legally effective, a CRZ approval exists, or construction is permissible.

**Legal verification:** every material conclusion must retain the relevant notification, gazette, sanctioned plan, approval, property card, CRZ/MCZMA record, ASI record or authority correspondence. A report must say `not found in this service` or `requires verification`, not `no restriction`, when the evidence chain is incomplete.

## Duplicate and near-duplicate layers

The audit found two duplicate families that must not be counted twice or merged by name alone:

* **57 and 61:** the live audit returned the same 4,332 object IDs and identical response hashes. Layer 61 is the operational canonical source; Layer 57 remains a related source that must be periodically revalidated for drift.
* **2250, 2251 and 2252:** the live audit returned 3,053 records from each with matching IDs/responses. Layer 2250 is the operational canonical CZMP source. Do not sum their areas or report three independent restrictions.

The deduplication contract is: preserve every source layer ID in provenance, derive one canonical finding only after an equivalence test, and retain a `duplicate_of`/`related_to` relationship rather than deleting source evidence. If duplicate layers disagree, report the disagreement and require review.

## Ranked candidate layers for the evidence module

The following are candidates from the live service audit, ranked by workflow value and risk. They are not enabled merely because they exist in the service.

| Rank | Candidate IDs | Likely workflow value | Gate before enabling |
|---:|---|---|---|
| 1 | 83, 2000 | Modification/EP/SM history and final planning decision context | Map aliases, decision/status vocabulary, dates and notification fields; prove final-vs-proposed precedence. |
| 2 | 92 | Sanction/approval or modification support record | Link every feature to an authoritative document; never treat a label as sanction proof. |
| 3 | 60, 61 | Reservation/designation context and possible legacy duplicate | Compare with 57/61 family and current 46/47; de-duplicate before area aggregation. |
| 4 | 85 | Reservation relocation/reconstitution, original CTS and approval context | Preserve original and relocated CTS references, approval and document; do not infer current effect from overlap alone. |
| 5 | 81 | Road realignment, width and approval context | Preserve approval/document fields and exact partial overlap; do not equate a small overlap with frontage. |
| 6 | 2250, 2251, 2252 | CRZ detail/alternate coverage | Prove relationship to 14/1264/1548, category precedence and geometry equivalence. |
| 7 | 57, 61 | Legacy/display duplicate family | Keep for audit comparison, not additive constraint area. |
| 8 | 77, 78, 79 | Heritage building, precinct and buffer context | Match identifiers to official heritage schedules; preserve unresolved remarks rather than inferring prohibition. |
| 9 | 29, 30 | ASI 100 m and 300 m outer extents | Derive the 200 m regulated band as 300 m minus 100 m; verify against the protected-monument record. |
| 10 | 16, 19, 20, 197, 1149, 48, 49 | Infrastructure/environmental screening | Geometry-only layers require explicit screening language and must not invent a legal setback. |
| 11 | 1210, 1211, 2400, TPS 105–112 | Settlement, amenity and legacy TPS context | Treat as contextual/inventory evidence; never use absence as proof of no restriction. |

Conditional candidates for later modules include TPS, Gaothan/Koliwada, SPA,
Gorai-Manori, amenities, railway/highway/infrastructure and coastal boundary
layers. Runtime interpretation should query/evaluate them only when the parcel's
location or an earlier finding makes them applicable; “all conclusions for
every parcel” is neither performant nor semantically safe. The local archival
snapshot now retains every canonical registry layer so future audits do not
depend on the live service, but the runtime parser remains curated and
conditional.

## Authority tiers

Every finding in the new module should carry an authority tier and evidence state:

| Tier | Meaning | Permitted product language |
|---|---|---|
| A — statutory/decision document | Gazette, sanctioned/final plan, approval/order, current authority record, or directly linked official document | “Source records state …”; still show date and document reference. |
| B — official MCGM GIS feature | Current MCGM service geometry/attributes with object ID, layer ID and query timestamp | “The parcel intersects … in the MCGM GIS service.” |
| C — official contextual overlay | Boundary, proposed layer, buffer, display/legacy copy, or layer whose legal effect is not established | “Context/warning; applicability and legal effect require verification.” |
| D — derived/inferred | Shapely intersection, area percentage, deduplication, chronology inference, AI summary or parser fallback | “Calculated/inferred from …”; never present as a statutory conclusion. |

An absent feature is not Tier A evidence of absence. A failed query is an unknown, and a conflicting Tier B result is a review item.

## Exact workflow value

The layers add value when they change an actionable decision, not when they lengthen the report:

* **Acquisition:** flag a reservation, sanctioned modification, CRZ overlap, heritage/ASI context or road realignment before land is priced.
* **Concept feasibility:** calculate a screened geometric envelope, while keeping review-only overlays outside the hard exclusion set.
* **Consultant coordination:** give architect, planner, lawyer and client one constraint register with object IDs, source links, timestamps and uncertainty.
* **Client reporting:** show the decision text and chronology rather than a bare `MODIFIED`/`YES` label.
* **Automated planning:** hand a typed, provenance-bearing envelope to a future massing solver; do not let an LLM invent setbacks or decide statutory precedence.
* **Portfolio screening:** compare sites with consistent risk flags and evidence quality.

The core geometric model is:

```text
parcel
  - confirmed reservation/designation/road/CRZ exclusions
  = screened developable envelope
```

That subtraction is only valid for layers whose legal and geometric meaning has passed the relevant gate. Heritage, refused/proposed EPs, contextual buffers and unresolved duplicates should initially generate warnings, not automatic land removal.

## CRZ findings and safeguards

The original CRZ implementation demonstrated two opposite failure modes:

1. **False positive:** district/boundary Layer 2238 (`Coastal Districts having CRZ`) covers broad portions of Mumbai. Its overlap is not proof that each parcel is in a CRZ zone.
2. **False negative:** the first replacement set (31, 1118, 2212, 2213, 2214, 2240, 2241, 2242, 2243) consisted of boundary/line layers. A centroid or polygon test against lines cannot establish a zone-polygon hit, so every parcel could silently return `NO`.

The validated production approach uses polygon layers **14, 1264 and 1548**, reads the tier from `category`, `Category`, `CATEGORY`, `CLASS` or `Class`, and reports values such as `YES (CRZ II)`. Coastal controls WORLI 886/947, BANDRA-A 409 and owner-reviewed WORLI 733 return CRZ II; inland controls BYCULLA 1605 and TARDEO 264 remain outside the CRZ polygon set. These are software controls, not a substitute for current CRZ/MCZMA confirmation.

The parser must collect all intersecting CRZ features across all configured layers before choosing a display tier. A “first match wins” loop is unsafe: layer order can change, one layer may have a blank category, and a broad/duplicate polygon may be encountered before the more specific feature. If tiers conflict or the category is absent, return `CRZ: REVIEW/UNKNOWN` with all source hits rather than silently choosing one.

For a polygon constraint, use exact parcel-wide intersection and report overlap area and percentage. A centroid hit is permitted only as a deliberately labelled fallback and can never be a negative proof for a polygon layer.

## ASI 100 m / 300 m geometry interpretation

The audit identified the need to distinguish the familiar archaeological-monument distances:

* **100 m:** prohibited area around a protected monument;
* **300 m outer extent:** the following 200 m regulated band lies between the 100 m and 300 m boundaries.

Those distances are useful screening semantics, but an MCGM overlay or a derived buffer is not automatically the legal boundary. The calculation must document the source monument geometry, coordinate system, buffer origin, units, and whether the source represents the protected monument boundary or only a point/label.

**Inference:** a layer that looks like a 100 m/300 m ring can be used to flag a possible ASI constraint and to guide document retrieval. It should not be used to remove land from a buildable envelope unless the monument, protected limits, notification and current ASI/competent-authority record agree.

**Legal verification:** confirm against [Archaeological Survey of India](https://asi.nic.in/), the current [India Code](https://www.indiacode.nic.in/) text and the applicable protected-monument notification. Measure from the legally recognised protected monument boundary, not from a centroid, label point, cadastral corner or visually convenient ring. Keep the 100 m and 300 m bands separate; do not collapse both into a generic “ASI buffer.”

## Current parser and query issues

### Layer 192 aliases and chronology

Layer 192 returns field names `LABEL` and `APPROVAL_DOCUMENTS`, whose aliases are `LABEL to Display` and `Approval Documents`. The current polygon parser reads the aliases, so it can replace real values with `Modified` and `None`. The parser must use the actual query field names with deliberate alias fallbacks and retain the original field/value. At minimum, support the observed `NEW_RES_*`, `NEW_DES_*`, `FINAL_*`, approval/order, decision/status, label and date variants.

`NEW_*` is not synonymous with `FINAL_*`. A proposed/new code, a final code, a correction, a refused EP and a sanctioned SM are different states. The current normalization fallback (`NEW_*` before `FINAL_*`) is safe for preserving a visible value but not safe as a legal precedence rule. The evidence module must expose both values and chronology, classify `NEW`, `PROPOSED`, `FINAL`, `SANCTIONED`, `REFUSED`, `CORRECTED` and `UNKNOWN`, and require a document when the chronology is incomplete.

### CRZ first match

As described above, do not stop at the first CRZ hit. Aggregate all hits, normalize tier/category aliases, retain layer/object provenance, detect conflicts and apply an explicitly versioned precedence policy.

### `outFields=*`

`outFields=*` is useful during discovery but is too broad for the production
evidence result. It increases response size, leaks irrelevant fields into logs,
couples the parser to schema churn and makes duplicate comparisons expensive.
Live runtime queries therefore request the registry allow-list. The local
archival downloader deliberately captures all source fields once; its runtime
adapter filters them back through the same allow-list before constructing a
finding. The allow-list includes the object ID, every recognised alias and the
required decision/date/document fields. Full raw attributes remain audit
storage, not report rendering.

### Geometry and errors

Validate ArcGIS `error` objects before interpreting `features`. Validate geometry type and rings before intersection; preserve holes and multipart parcels. Treat timeout, HTTP error, malformed JSON, empty-but-unexpected response and unsupported geometry as `UNKNOWN`/incomplete. Never write a confident `NO`, cache a degraded result or deduct area from a failed query.

## Performance and operating envelope

The existing pipeline is already fast enough for a curated lookup, but broadening it indiscriminately will recreate the service-throttling problem. The evidence module should:

* query the parcel once and reuse its bounded envelope;
* use a registry to run only applicable families;
* query a small, allow-listed field set;
* cap concurrency and back off on MCGM throttling;
* cache only complete, provenance-bearing results with service/query timestamps;
* compute intersections locally after bounded responses;
* separate the fast planning answer from reports, maps and document retrieval; and
* publish timings per layer family, not just one total duration.

Initial engineering budgets should be treated as gates, not promises: no regression to the existing warm planning-half baseline (roughly 0.7 s on the established fixture), no unbounded increase in request count, and a bounded full-evidence mode with an explicit slow-path label. Measure cold and warm runs on all ten controls, including throttled/error cases.

## Acceptance gates before exposing candidate layers in public conclusions

1. **Metadata snapshot:** save service root, layer metadata, field aliases, geometry type, edit information, query capabilities and an audit timestamp.
2. **Corpus:** every one of the ten stable parcel IDs has a raw response manifest and a deterministic rerun test.
3. **Positive/negative controls:** coastal CRZ positives remain positive; inland negatives remain negative; partial overlaps report non-zero area and percentage.
4. **Duplicate proof:** 57/61 and 2250/2251/2252 have spatial/attribute comparison reports; no duplicate area is double-counted.
5. **Layer 192 parser:** aliases, `NEW`/`FINAL`, dates, status and refusal/sanction states are preserved and tested.
6. **CRZ precedence:** all hits are collected; missing/conflicting categories produce review/unknown, never a guessed tier.
7. **ASI geometry:** 100 m and 300 m are separate, unit-tested derived bands with source geometry and a legal-verification warning.
8. **Failure closed:** service errors, timeouts, malformed features and empty unexpected responses cannot create a confident absence or cached success.
9. **Evidence contract:** every finding contains layer ID, object ID, source URL, query timestamp, raw/normalised attributes, authority tier and confidence/evidence state.
10. **Performance:** cold/warm timing, request count, response bytes and throttling are recorded; full mode stays within an agreed operational budget.
11. **Human review:** an architect/planner and a legal/regulatory reviewer sign off the interpretation of statutory, proposed, contextual and derived layers.
12. **Report language:** outputs distinguish “intersects MCGM GIS feature” from “legally applicable”; no automatic FSI or buildable-area conclusion is emitted from an unverified overlay.

## Implementation validation — 18 August 2026

The first optional implementation was validated without changing the default `basic` lookup or Layer 13 ingestion contract:

* offline: Ruff clean, strict mypy clean, 249 tests passing, 83.64% branch-aware coverage, with wheel and source-distribution builds verified;
* `COLABA 1/600 --evidence standard`: core and optional evidence complete; eight findings comprising EP-A18, two SM-history records, one EP-history record and four CZMP categories. CZMP overlap was reported separately as CRZ II 38.534%, NDZ within CRZ II 34.861%, CRZ IVA 5.117% and CRZ IB 21.488%; no category was discarded by first-match logic;
* `MULUND-E 637 --evidence standard`: retained the raw Layer 83 decision `Refused to accord sanction. The proposal as per Section 26 is reinstated.` with its notification/gazette reference and 9.456% overlap; it was not converted into an approved/sanctioned boolean;
* `VILE PARLE 1449 --evidence full`: complete 27-layer pass, one 100% Gaothan finding (`Vile Parle Gaothan`) and no malformed/failed layer. Total live lookup was about 8.8 seconds; Layer 2000 alone was a 7.6-second server outlier, confirming the need for bounded concurrency and a separate slow-path mode; and
* `PRINCESS DOCK 139 --evidence full`: the Layer 112 TPS-property detector activated the TPS family, Layer 107 returned the expected TPS reservation, and CZMP 2019 returned a 100% NDZ-within-CRZ-II screening hit.

These are reproducible engineering observations from the external service on the date above. They are not legal certificates, and future runs can change if MCGM edits the source service.

## Planning snapshot archival validation — 21 August 2026

The later local-source phase archived all 52 canonical registry layers and
65,604/65,604 official inventory records. This changes source availability, not
the authority rules above: only curated/conditional layers enter runtime
findings, and spatial overlap remains screening evidence.

The full build exposed two official-source details now preserved in code and
the manifest:

- Metro influence zones, traffic road alignments and water bodies use the true
  OID field `OBJECTID_1`; the downloader now discovers OID and geometry type
  from official layer metadata instead of trusting a registry default.
- Designation layer 47 records 1158, 1159 and 4817 exist in the official
  inventory but publish empty rings. They are kept as complete attribute
  records and explicit geometry warnings; no geometry is fabricated.

Activation required 15/15 live/local core-planning matches and 5/5 full
optional-evidence matches. Three fresh CLI runs then produced all seven
artifacts with complete local planning evidence and no result warning. Current
offline gates are 399 passing tests, 84.48% branch-aware coverage, Ruff clean
and strict mypy clean. The detailed record is
[`audits/PLANNING-SNAPSHOT-VALIDATION-2026-08-21.md`](audits/PLANNING-SNAPSHOT-VALIDATION-2026-08-21.md).

## Safe rollout sequence

1. Keep the current lookup and validated CRZ set unchanged; add no new layer to the existing conclusion path.
2. Create a versioned layer registry and metadata snapshot/audit log. Make field aliases and authority tier explicit.
3. Add candidate queries in **shadow mode**. Store raw responses, timings, geometry hashes and parser findings without changing the public result.
4. Compare duplicate families and run the ten-CTS corpus. Resolve field/chronology conflicts before aggregation.
5. Add typed evidence and constraint models. Keep confirmed geometric exclusions separate from review-only warnings.
6. Enable only the current validated CRZ polygon behaviour behind the evidence module, with all-hit aggregation and explicit unknown/conflict states.
7. Enable modification, heritage, ASI and infrastructure candidates one family at a time after their acceptance gates pass.
8. Expose an optional `basic`/`full` evidence mode and an evidence register in JSON/report outputs. The existing fast lookup remains the safe default.
9. Have domain reviewers validate representative reports and the source-document links. Record rule-set and parser versions with every result.
10. Only after the evidence contract is stable should the screened envelope be consumed by a massing/planning solver.

The module is therefore a planning due-diligence aid, not a replacement for a sanctioned plan, development permission, title search, CRZ clearance, ASI decision or professional legal advice.

## Official references

* [MCGM Development Plan 2034 MapServer root](https://agsmaps.mcgm.gov.in/server/rest/services/Development_Plan_2034/MapServer)
* [MCGM Layer 13 parcel metadata](https://agsmaps.mcgm.gov.in/server/rest/services/Development_Plan_2034/MapServer/13)
* [MCGM Layer 192 modification metadata](https://agsmaps.mcgm.gov.in/server/rest/services/Development_Plan_2034/MapServer/192)
* [MCGM CRZ polygon layer 14](https://agsmaps.mcgm.gov.in/server/rest/services/Development_Plan_2034/MapServer/14), [1264](https://agsmaps.mcgm.gov.in/server/rest/services/Development_Plan_2034/MapServer/1264), [1548](https://agsmaps.mcgm.gov.in/server/rest/services/Development_Plan_2034/MapServer/1548)
* [ArcGIS REST API: Query (official Esri documentation)](https://developers.arcgis.com/rest/services-reference/enterprise/query-feature-service-layer/)
* [Archaeological Survey of India](https://asi.nic.in/)
* [India Code](https://www.indiacode.nic.in/)
