# Tooling and dependency policy

**Date:** 2026-11-24
**Status:** Accepted
**Affects:** `pyproject.toml`, `.github/workflows/ci.yml`

Moved from `pyproject.toml` and CI comments; see
[2026-11-24 no code comments](2026-11-24-no-code-comments.md).

## Dependency floors

- `pillow>=13.0.0`: Pillow 13 fixes image-decoder advisories in older
  releases.
- `certifi>=2026.10.19`: keeps the TLS trust-store fix even when installing
  without `uv.lock`.
- `matplotlib` is a `dev` extra only because `tools/render_dxf.py` uses it.

## Ruff

Rules are chosen to catch defects, not style: `E`, `F`, `I`, `B`, `RUF`.
Deliberately excluded:

- `UP`/`FA` (`Dict` → `dict` modernisation, `__future__` annotations): pure
  churn with no behaviour change; the project keeps explicit
  compatibility-facing annotations.
- `DTZ` (naive datetimes): timestamps are local report times read by people
  in one city; timezone-aware values add noise, not safety.
- `S110` (`try`/`except`/`pass`): several are deliberate (optional ezdxf
  linetypes) and are reviewed by hand.
- `E501` stays disabled for generated markup, ArcGIS schema and drawing
  declaration lines where wrapping hurts readability.

## Pytest

Project and runtime warnings stay visible. Only ezdxf's upstream pyparsing
compatibility-alias deprecations are filtered.

## Mypy

Strict checking covers the whole `dp_lookup` package. The named third-party
rendering packages without inline types (`ezdxf`, `openpyxl`, `qrcode`,
`reportlab`, `shapely`) are the only modules outside that boundary.

## CI

The pytest matrix runs from the oldest supported Python (`requires-python`)
to the current release with `fail-fast` off, so every failing version is
reported. The suite is fully offline and never contacts MCGM servers; live
checks live in the separate `live-smoke` workflow.
