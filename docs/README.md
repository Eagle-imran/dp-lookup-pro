# Documentation

This is the navigation page for current project documentation. Start with the
plain-English [quick start](../START-HERE.md) to run a lookup, or the main
[README](../README.md) for installation and complete CLI usage.

## Current system

| Area | Use it for |
| :--- | :--- |
| [Architecture](architecture/overview.md) | Dependency direction, query stages, extension points and ArcGIS ingestion guarantees |
| [Local spatial database](operations/local-spatial-database.md) | Parcel/planning snapshot design, local-first lookup and source-of-record policy |
| [Planning snapshots](operations/planning-snapshots.md) | Building, verifying, activating and rolling back planning data |
| [ArcGIS layer reference](reference/arcgis-layers.md) | Audited source layers, fields, limitations and authority notes |
| [Planning evidence](guides/planning-evidence.md) | Evidence modes and what additional layers add to a study |
| [Certified sources](guides/certified-sources.md) | Adding, reviewing and activating Property Cards, surveys and CTS/FP plans |
| [Plot intelligence](guides/plot-intelligence.md) | Building and querying portfolio-ready derived facts |
| [Experimental plot assemblies](guides/experimental-plot-assemblies.md) | Opt-in neighbouring-CTS union and amalgamation feasibility study |
| [DXF guide](guides/dxf.md) | Reading and handing off the architectural CAD output |
| [Rollback](operations/rollback.md) | Safe recovery when a release or snapshot causes a problem |
| [Performance regression](operations/performance-regression.md) | Offline stage-latency gate and limits of live timing claims |

## Project record

- [Changelog](project/changelog.md) records shipped and unreleased changes.
- [Roadmap](project/roadmap.md) separates future work from current capability.
- [Engineering history](project/engineering-history.md) retains older technical
  context; current contracts live in the architecture and operations sections.
- [Decisions](decisions/README.md) contains dated design proposals and decisions.
- [Audits](audits/README.md) contains dated validation evidence, including the
  current local-first acceptance and source baseline.
- [Archive](archive/) contains superseded documentation and must not be treated
  as the current implementation contract.

## Documentation rules

- Keep one current source of truth for each topic and link to it from here.
- Put operational procedures in `operations/`, user workflows in `guides/`,
  external-source facts in `reference/`, and dependency contracts in
  `architecture/`.
- Name dated evidence and decisions with `YYYY-MM-DD-...`.
- Update links and documentation contract tests whenever a document moves.
- Do not commit generated reports, local SQLite databases, caches or build
  artifacts.
