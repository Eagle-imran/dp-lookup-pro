# Development status

Updated 2026-10-23. Current scope is plot-intelligence activation and existing
defects. FSI calculations and a web application remain separate roadmap work.

## Main baseline

`main` and `origin/main` were synchronized at `e375807` after merging
[maintenance PR #5](https://github.com/Eagle-imran/dp-lookup-pro/pull/5).
Maintenance and dependency branches were removed after their commits were
incorporated. The checkpoint is retained as the remote
`checkpoint-pre-2026-08-18` tag. New work lives on `codex/development`.

The baseline uses uv 0.13.5, GitHub CLI 2.103.0, Ruff 0.17.2, mypy 2.4.0 and
stable Python 3.15.1 for development. Supported Python starts at 3.11. The
patched lockfile passes runtime and development dependency audits; all four
Python CI jobs, strict typing, formatting, packaging and CodeQL passed on main.
See the [maintenance audit](../audits/REPOSITORY-MAINTENANCE-2026-10-23.md).

## Development changes

- Repair overlapping or edge-sharing multipart analysis geometry and retain
  quality flags, source coordinates and the recorded-area comparison.
- Bound and reuse immutable-snapshot planning geometries rather than decoding
  large CRZ and other layer features for each plot. Avoid unused road drawings
  during intelligence derivation.
- Make build resumption require matching selected ranges and analysis options.
  Validate source, authority and algorithm fingerprints before publication and
  default queries; keep explicit historical build IDs available for audit.
- Preserve build parameters in existing validation metadata, without a schema
  migration. Count newly inserted intelligence records incrementally.
- Use calculated ground square metres for neighbours lacking a consistent
  recorded area. Invalidate report cache entries from the older analysis policy.
- Remove quadratic inventory membership and duplicate checks from ingestion.
- Retry malformed inventory and feature response shapes within the bounded
  request retry policy, preserving staged data for a later resume.
- Add selected-layer planning refreshes with exact local copying, upstream
  change/drift checks and independent incremental resume state.

These changes use intelligence algorithm `plot-intelligence/1.4.0` and report
cache schema 2. They are not yet part of the main baseline above.

## Measured validation

The original fresh 25-identity sample at offset 50,000 failed GUNDAVALI CTS 343
because overlapping source parts produced an invalid MultiPolygon. The repaired
sample completed 25/25, retained its warnings and source references, and fell
from 25.722 seconds to 2.181 seconds under the same profiling setup.

A separate 1,000-identity full-evidence sample completed without errors in
32.107 seconds with one worker; four workers took 41.383 seconds. One worker is
therefore the default. These are sample measurements, not a citywide timing
guarantee or a completed publication.

The current offline suite passes 567 tests with 84.30% coverage. Formatting,
Ruff and strict typing pass. CI results are available on
[development PR #6](https://github.com/Eagle-imran/dp-lookup-pro/pull/6). The
previous code baseline passed all four Python versions, packaging, dependency
auditing and CodeQL.

## Active data and remaining development

The targeted update activated parcel snapshot 3 (135,365 records; 119,548
queryable identities) and planning snapshot 5 (65,624 records across 52 layers).
Reused the previously staged parcel archive, rechecked all 66 added/edited
payloads and confirmed 3 removals. Downloaded six planning layers and copied
the remaining 46 locally; all 27 added/edited planning payloads match live data.
Final upstream fingerprints report no changes or unknown layers. Database
integrity passes with zero critical findings. See the
[targeted update audit](../audits/TARGETED-SOURCE-UPDATE-2026-10-23.md).

Former active snapshots are retained for rollback. The abandoned full planning
snapshot 4 retains its partial data but is marked superseded/failed to prevent
accidental resumption. No whole planning refresh was completed or restarted.

Remaining plot-intelligence work:

- Build every queryable village/CTS identity with full evidence and neighbours,
  resolve derivation errors, verify and activate the matching full build.
- Exercise default analyze, search and comparison and record publication
  evidence. No full intelligence build was started during this source update.

Operational databases, retained snapshots, report bundles and certified source
files remain outside Git. Existing data and reports are preserved.
