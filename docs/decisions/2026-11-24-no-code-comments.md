# No code comments

**Date:** 2026-11-24
**Status:** Accepted
**Enforced by:** `tools/check_comments.py` (CI `ruff` job and
`tests/test_comment_ratchet.py`)

## Context

An audit of every code comment found 194 comment blocks in Python plus about 60
lines in the map templates, `pyproject.toml` and CI. They fell into four kinds:

| Kind | Blocks | What it is | Action |
| :--- | ---: | :--- | :--- |
| Tautology | 107 | Repeats what the code already shows | Deleted |
| Stale | 9 | Describes an implementation or bug that no longer exists | Deleted |
| Excuse | 20 | Justifies a workaround, so the workaround spreads | Deleted; issue filed |
| Decision record | 58 | An important, non-obvious decision | Moved to an ADR |

Comments drift from the code they describe, and excuse comments make a hack
look intentional, so later changes copy it. Decisions that matter belong
in one place that is reviewed as documentation.

## Decision

- Code carries no comments. Names, types and tests explain *what*. Decision
  records in `docs/decisions/` explain *why*.
- Docstrings are allowed; they are documentation and part of the API.
- Tool directives are allowed: shebangs, encoding cookies, `noqa`,
  `type: ignore`, `pragma: no cover`, `fmt:`/`ruff:`/`mypy:`/`pyright:` markers,
  `nosec`, and pinned-action version tags (`# v10.3.3`) that Dependabot reads.
- A comment that would explain a magic number becomes a named constant, test
  ID or variable name instead.

## Ratchet

`tools/check_comments.py` scans tracked Python, JS, CSS, HTML, TOML and YAML
outside `docs/`, `output/` and `data/`. `tools/comment_baseline.json` records
how many comments each file may still hold. A file may never exceed its count,
and files not listed may hold none. When comments are removed the check fails
until `--update` lowers the baseline, so the allowance only shrinks.

After this change the baseline is empty: every comment in scope was
removed. The baseline exists so a later, wider scope (for example `.gitignore`
or docstrings) can be adopted gradually instead of in one change.

To repeat the cleanup, run the `/delete-comment` skill in
`.claude/skills/delete-comment/`.

## Where the decisions went

- [Parcel identity, split parcels and plot area](2026-11-24-parcel-identity-and-area.md)
- [Coordinate systems and units](2026-11-24-coordinate-systems.md)
- [MCGM source ingestion and snapshots](2026-11-24-source-ingestion.md)
- [Caching, locking and concurrency](2026-11-24-caching-and-concurrency.md)
- [Authority sources and plot intelligence records](2026-11-24-authority-and-intelligence-records.md)
- [Report, drawing and CLI behaviour](2026-11-24-outputs-and-cli.md)
- [Tooling and dependency policy](2026-11-24-tooling-policy.md)
