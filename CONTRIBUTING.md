# Working on `dp-lookup-pro`

## Setup

```bash
uv sync --frozen --all-extras --dev
```

## Before you push

CI enforces the same gates locally and remotely:

```bash
uv lock --check
uv run ruff check .
uv run mypy
uv run pytest -q --cov --cov-report=term-missing
uv export --frozen --no-dev --no-emit-project --no-hashes \
  --format requirements-txt --output-file /tmp/dp-lookup-runtime.txt -q
uv run pip-audit -r /tmp/dp-lookup-runtime.txt
```

The test suite never touches the MCGM servers, so it is safe to run repeatedly.

## What CI checks

| Job | What it does |
| :--- | :--- |
| `ruff` | Lint and format checks with the rules in `pyproject.toml` |
| `typing, coverage, dependency audit` | Strict package-wide typing, branch-aware 83% coverage ratchet, and runtime vulnerability audit |
| `build` | Builds distributions and installs the wheel in a clean environment |
| `pytest` | Full offline suite across the supported CI Python versions |
| CLI smoke | The installed command reports help/version and lists all 128 villages |

Separate workflows run CodeQL, review dependency changes, exercise one real
uncached MCGM lookup on weekdays, and publish only version-matching tags through
PyPI trusted publishing with checksums and provenance attestations. The live
smoke is intentionally not part of pull-request CI because upstream availability
is outside this repository's control.

Python 3.9 is in the matrix because `requires-python` claims support for it —
verified, not assumed.

## Lint rules

`select = ["E", "F", "I", "B", "RUF"]`. Chosen for defects rather than style.
Deliberately excluded, with reasons recorded in `pyproject.toml`:

- **UP / FA** — `Dict`→`dict` modernisation and `__future__` annotations. Churn
  across 17 sites with no behaviour change.
- **DTZ** — naive datetimes. These are local report timestamps for one city.
- **S110** — `try/except/pass`. Several are deliberate (optional ezdxf
  linetypes); reviewed by hand rather than gated.
- **E501** — retained because generated markup, ArcGIS schemas and drawing
  declarations contain a small number of intentionally indivisible lines.
  New application and client code still follows the 120-column convention.

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
