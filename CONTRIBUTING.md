# Working on `dp-lookup-pro`

## Setup

```bash
uv sync --frozen --all-extras --dev
```

The checkout pins Python 3.15.1 in `.python-version`; `uv` can install it on
first sync. The package's minimum supported runtime remains Python 3.11.

## Before you push

CI enforces the same gates locally and remotely:

```bash
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run python tools/check_comments.py
uv run mypy
uv run pytest -q --cov --cov-report=term-missing
uv export --frozen --no-dev --no-emit-project --no-hashes \
  --format requirements-txt --output-file /tmp/dp-lookup-runtime.txt -q
uv run pip-audit -r /tmp/dp-lookup-runtime.txt
```

The test suite never touches the MCGM servers, so it is safe to run repeatedly.
Apply formatting with `uv run ruff format .`; it covers the whole repository.

## What CI checks

| Job | What it does |
| :--- | :--- |
| `ruff` | Lint and format checks with the rules in `pyproject.toml`, plus the code-comment ratchet |
| `typing, coverage, dependency audit` | Strict package-wide typing, branch-aware 83% coverage ratchet, and runtime vulnerability audit |
| `build` | Builds distributions and installs the wheel in a clean environment |
| `pytest` | Full offline suite across the supported CI Python versions |
| CLI smoke | The installed command reports help/version and lists all 128 villages |

Separate workflows run CodeQL, review dependency changes, exercise one real
uncached MCGM lookup on weekdays, and publish only version-matching tags through
PyPI trusted publishing with checksums and provenance attestations. The live
smoke is intentionally not part of pull-request CI because upstream availability
is outside this repository's control.

Python 3.11 is the supported minimum because the patched Pillow 13 dependency
requires it. CI exercises Python 3.11, 3.13, 3.14 and 3.15; strict mypy checks the
3.11 language baseline. Python 3.9 and 3.10 require older Pillow releases with
known advisories and are no longer supported.

## Lint rules

`select = ["E", "F", "I", "B", "RUF"]`. Chosen for defects rather than style.
Deliberately excluded, with reasons recorded in the
[tooling policy ADR](docs/decisions/2026-11-24-tooling-policy.md):

- **UP / FA** — `Dict`→`dict` modernisation and `__future__` annotations. Churn
  across 17 sites with no behaviour change.
- **DTZ** — naive datetimes. These are local report timestamps for one city.
- **S110** — `try/except/pass`. Several are deliberate (optional ezdxf
  linetypes); reviewed by hand rather than gated.
- **E501** — retained because generated markup, ArcGIS schemas and drawing
  declarations contain a small number of intentionally indivisible lines.
  New application and client code still follows the 120-column convention.

## Code comments

Code comments are not allowed; see the
[no code comments ADR](docs/decisions/2026-11-24-no-code-comments.md).
Explain *what* with names, types and tests, and record *why* in
`docs/decisions/`. Docstrings and tool directives (`noqa`, `type: ignore`,
`pragma: no cover`) are fine. `tools/check_comments.py` enforces a per-file
ratchet from `tools/comment_baseline.json`; after removing comments, run it with
`--update`. The `/delete-comment` Claude Code skill repeats the full cleanup.

## Testing against the live server

The MCGM server **rate-limits sustained bursts**. When running real lookups back
to back, space them ~10 s apart or you will get `ReadTimeout` errors that are not
real failures. Known-good plots for manual checks:

| Plot | Expect |
| :--- | :--- |
| `WORLI 733` | CRZ II — owner-verified |
| `BYCULLA 1605` | Inland, no CRZ; MODIFIED status |
| `MALABAR HILL 518` | RESERVED / designated |
| `BANDRA-A 409` | Small plot; 6 m setback correctly omitted |

Pass `--no-cache` when re-testing, or a cached result can replay old behaviour
and make a fix look like it failed.

Set `DP_LOOKUP_LOG_JSON=1` to emit one structured JSON event per application
stage to stderr. Every result also contains `metadata.diagnostics.run_id`, total
elapsed time, and stage timings for correlation without a logging dependency.

## Rendering a DXF to look at it

```bash
uv run python tools/render_dxf.py output/worli_cts_733/plot_G-S_733_worli.dxf --zoom
```

Geometry checks prove a drawing is correct; they cannot tell you it is readable.
