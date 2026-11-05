# Maintainer tools

These scripts are developer utilities, not public CLI commands:

- `check_format.py` checks the shared local/CI Ruff formatting scope. Pass
  `--fix` to apply formatting to that same target list.
- `audit_dxf.py` checks a generated DXF for layout, collision and disclosure
  faults and returns a non-zero exit code on failure.
- `render_dxf.py` renders a DXF to PNG for visual inspection and requires the
  development dependency set.
- `acceptance_audit.py` runs a deterministic 15–25 CTS local-versus-live
  acceptance gate across identity, raw geometry checksum, area, planning
  evidence and the complete output bundle. It requires an active local parcel
  and planning database plus network access to MCGM ArcGIS.
- `intelligence_acceptance.py` checks a ready or active intelligence build
  entirely offline: identity coverage, recomputed fact hashes, source references,
  normal-lookup parity and public CLI search/comparison. For example:

  ```bash
  uv run python tools/intelligence_acceptance.py \
    --database data/mcgm-layer13.sqlite --build-id BUILD_ID \
    --sample-size 25 --json-report /tmp/intelligence-acceptance.json
  ```

  Add `--require-active` after publication to check default queries and source
  alignment. `--allow-sample` is only for testing a non-publishable sample.
  The tool neither downloads source data nor activates a build. Plot totals
  follow their selected recorded/calculated area basis; source-intersection
  square metres retain their digitized boundary basis.

The offline stage-latency regression is maintained as a test rather than a
runtime tool. Run `uv run pytest -q tests/test_stage_latency_regression.py`;
see [the performance regression runbook](../docs/operations/performance-regression.md)
for its injected delays, thresholds and interpretation.

Run them from the repository root with `uv run python tools/<script>.py ...`.
