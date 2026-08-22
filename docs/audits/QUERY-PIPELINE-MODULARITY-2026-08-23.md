# Query pipeline modularity audit — 2026-08-23

## Scope

This pass covered the complete path from CLI input through parcel acquisition,
planning evidence, geometry, output orchestration and persistence reads. The
non-negotiable compatibility constraint was that the MCGM ArcGIS request
fields, layer IDs, output spatial reference, local-first fallback policy,
public CLI and generated artifact formats must continue to work.

## Structural changes

- `cli.py` remains a small compatibility router over parser, bootstrap,
  execution and presentation modules.
- ArcGIS HTTP JSON is decoded once into immutable `ArcGISPayload` and
  `ArcGISFeature` objects. Valid empty collections and malformed collections
  are different states.
- Road, neighbour and planning normalization are independent stages;
  `application/normalization.py` is a 12-line compatibility facade.
- The normal PDF/Excel path consumes typed `PlotReportData` and
  `ExcelRegisterData`. Legacy long signatures are retained only for existing
  direct callers and explicitly injected test/integration writers.
- DXF and PDF public modules are small stable facades. DXF policy, geometry,
  text collision, legend and ezdxf rendering remain replaceable subsystems.
- Planning snapshot spatial reads live in `planning_snapshot/query.py`, apart
  from snapshot build, validation, activation and rollback.
- Cache reads/writes and all artifact writers remain injected ports.

## Enforced gates

| Gate | Requirement |
| :--- | :--- |
| Static typing | Strict mypy over the complete `dp_lookup/` package |
| Lint | Ruff defect/import rules, zero findings |
| Tests | Complete offline suite with branch-aware coverage |
| Coverage ratchet | At least 83% branch-aware coverage |
| Architecture | AST/source contracts prevent layer-direction and facade regressions |
| Packaging | Source distribution and wheel build; wheel content inspection |
| Source compatibility | Offline ArcGIS request/fallback contract tests |
| Live compatibility | Fresh no-cache MCGM lookup plus artifact structure validation |

## Honest scoring policy

“10/10” here means the pipeline has an explicit responsibility, a typed or
validated boundary, a replaceable adapter where replacement is realistic, and
an automated regression gate. It does not mean the software can never contain
a defect. External ArcGIS uptime, source accuracy and legal authority are data
limitations and are not converted into software-quality claims.

## Offline verification

- 504 tests passed.
- Branch-aware coverage: 83.96% against the raised 83% ratchet.
- Ruff: clean.
- Strict mypy: clean across all 103 production modules.
- Focused ArcGIS ingestion, local/live fallback, typed export and compatibility
  regression suites passed before the complete suite.

## Package verification

- `uv build` produced both the source distribution and wheel.
- Wheel inspection confirmed the PEP 561 marker, packaged HTML/CSS/JS assets,
  typed ArcGIS models, focused normalizers, planning query repository, and DXF
  and PDF render implementations.

## Live ArcGIS smoke

Command: fresh no-cache, forced-live lookup for `WORLI / 733`.

- Complete: yes; warnings: none; cached: no.
- Total: 21.84 s; Layer 13 parcel ingestion: 197.5 ms; external source
  queries: 21.02 s; all local normalization/export work remained sub-second.
- Recorded plot area: 1,317.74 m²; calculated boundary area: 1,317.73 m².
- Zone R; CRZ II; three adjoining plots; named abutting road.
- Seven plot artifacts plus the shared Excel register were produced.
- PDF: two Letter pages; images: 1000×1000 and 768×768; DXF: R2010/AC1024,
  107 readable entities; GeoJSON: valid FeatureCollection; KML: valid XML;
  HTML: no unresolved template tokens; Excel: 43 columns and one data row.

This verifies that the refactor did not alter the live Layer 13 query path or
the complete output bundle contract.
