# Planning evidence capability

## Executive summary

The planning-evidence capability extends the existing DP lookup with a source-backed due-diligence register. It does not replace Layer 13 parcel ingestion, the established planning result, a sanctioned plan, an official DP Remark, title review, or professional legal advice.

The main workflow remains unchanged in `basic` mode. Expanded modes query curated additional layers only after Layer 13 has returned and validated the parcel geometry. Results are added under:

```text
metadata.evidence.planning_due_diligence
```

No expanded finding automatically changes the existing status badge or subtracts land from the developable envelope. It first records what intersected, how much, which source feature supplied it, and whether the record is statutory, regulatory screening, or contextual evidence.

## Runtime modes

```bash
dp-lookup-pro WORLI 733 --evidence basic
dp-lookup-pro COLABA 1/600 --evidence shadow --no-cache --json
dp-lookup-pro COLABA 1/600 --evidence standard --no-cache --json
dp-lookup-pro "VILE PARLE" 1449 --evidence full --no-cache --json
```

| Mode | Behaviour |
|---|---|
| `basic` | Existing lookup only. This is the compatibility default and uses the existing cache key. |
| `shadow` | Queries the curated standard set and records its independent audit result without affecting the core result, warnings or exit status. Incomplete evidence profiles are not cached. |
| `standard` | Queries the highest-value decision/correction layers and consolidated CZMP 2019 source. Incomplete optional evidence is visible in its own result. |
| `full` | Adds audited heritage, ASI, infrastructure, environmental, settlement and amenity sources. TPS, SPA and Gorai-Manori families are activated only after an applicability-boundary hit. |

Non-basic cache entries are namespaced by evidence mode and registry version. A cached `basic` result can therefore never satisfy a `standard` or `full` request. `--no-cache` bypasses the existing entry; a complete refreshed lookup is then stored normally, while incomplete core or optional evidence is not cached.

## Architecture and understanding

```text
Layer 13 parcel ingestion (unchanged, required)
        │
        ├── existing zoning/planning/road/report pipeline
        │
        └── optional planning-evidence adapter
                ├── typed immutable models
                ├── audited layer registry
                ├── explicit ArcGIS out-fields
                ├── bounded concurrency (maximum four layer requests)
                ├── local exact polygon intersections
                ├── per-layer hit/absence/failure/malformed/truncated state
                └── independent evidence report in metadata
```

The operational registry is in `dp_lookup/planning_evidence/registry.py`. Network/query behaviour is isolated in `dp_lookup/clients/planning_evidence_queries.py`. The application accesses it through `LookupDependencies`, so tests, future UIs, or a different GIS adapter can replace it without editing the cadastral ingestion stage.

Every finding preserves:

- layer ID and service name;
- ArcGIS object ID;
- source URL;
- evidence class and role;
- exact overlap area and parcel percentage;
- explicit, allow-listed source attributes;
- record-level provenance warnings;
- layer query duration and outcome; and
- retrieval timestamp, registry version and disclaimer.

`NOT_PRESENT` is emitted only after a successful, non-truncated query with usable geometry. A timeout, ArcGIS error object, malformed feature or transfer-limit response receives its own state and cannot become a confident negative.

## Authority model

| Evidence class | Product meaning |
|---|---|
| `statutory` | A record carrying decision/notification/gazette provenance that passed the registry's conservative record checks. It remains evidence of the recorded decision, not an automatic conclusion that a proposal was sanctioned. |
| `regulatory` | Official MCGM geometry or correction/approval evidence used for spatial screening and document review. |
| `contextual` | History, inventory, settlement, port, TPS or other context that must not be treated as a current statutory restriction by itself. |

Layer 83 deliberately retains raw sanction/refusal text because a feature in `Sanctioned_EP` can record a refused proposal and reinstated provision. Layer 2000 records with a `Test` approver or missing notification are downgraded from statutory to regulatory evidence. Generic approval-document directory values are explicitly warned about.

## Deterministic versus interpretive work

Deterministic:

- registry selection and duplicate canonicalisation;
- bounded ArcGIS request construction;
- response/error-state validation;
- multipart/hole-aware polygon conversion;
- exact intersection area and percentage;
- CRZ category collection;
- ASI 100 m versus derived outer 200 m band screening; and
- evidence serialization and provenance.

Requires professional or legal interpretation:

- whether a notification is currently effective;
- precedence between sanctioned plans, EPs, SMs and later corrections;
- whether a mapped buffer creates a legally applicable setback;
- whether contextual inventory is current; and
- whether a finding changes permissible FSI, use, height or developability.

An LLM may summarise raw remarks or help a user find conflicting evidence. It must not invent regulations, choose statutory precedence, or convert a spatial overlap directly into permission/prohibition.

## Audit record

The complete live-layer investigation, controls, duplicates, positive CTS examples, known parser problems, authority caveats and rollout gates are preserved in [ARCGIS_LAYER_AUDIT.md](ARCGIS_LAYER_AUDIT.md). Revalidate that audit whenever the external service schema, registry version, or interpretation policy changes.
