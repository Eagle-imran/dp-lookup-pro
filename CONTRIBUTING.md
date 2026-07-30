# Working on `dp-lookup-pro`

## Setup

```bash
uv sync --all-extras --dev
```

## Before you push

CI runs both of these, so run them locally first:

```bash
uv run ruff check .     # lint
uv run pytest -q        # 70 offline tests, no network
```

The test suite never touches the MCGM servers, so it is safe to run repeatedly.

## What CI checks

| Job | What it does |
| :--- | :--- |
| `ruff` | Lint with the rule set in `pyproject.toml` |
| `pytest` | Full suite on Python 3.9, 3.11 and 3.13 |
| CLI smoke | The command starts, prints usage, and lists all 128 villages |

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
- **E501** — 13 long lines are ArcGIS request payloads validated against the
  live server. Deferred until `lookup_plot_pro` (730 lines) is split.

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

Clear `output/.cache_store.json` before re-testing, or a cached result will
replay the old behaviour and make a fix look like it failed.

## Rendering a DXF to look at it

```bash
uv run python tools/render_dxf.py output/worli_cts_733/plot_G-S_733_worli.dxf --zoom
```

Geometry checks prove a drawing is correct; they cannot tell you it is readable.
