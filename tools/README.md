# Maintainer tools

These scripts are developer utilities, not public CLI commands:

- `audit_dxf.py` checks a generated DXF for layout, collision and disclosure
  faults and returns a non-zero exit code on failure.
- `render_dxf.py` renders a DXF to PNG for visual inspection and requires the
  development dependency set.
- `acceptance_audit.py` runs a deterministic 15–25 CTS local-versus-live
  acceptance gate across identity, raw geometry checksum, area, planning
  evidence and the complete output bundle. It requires an active local parcel
  and planning database plus network access to MCGM ArcGIS.

Run them from the repository root with `uv run python tools/<script>.py ...`.
