"""Typed output-artifact orchestration for a completed parcel lookup."""

from __future__ import annotations

import os
from typing import List, Optional

from dp_lookup.application.artifacts import run_artifact, run_artifact_in_thread, run_artifact_result
from dp_lookup.application.contracts import ArtifactContext, MapFetchContext, ReportArtifactContext
from dp_lookup.application.dependencies import LookupDependencies
from dp_lookup.application.exporting import (
    ArtifactExporter,
    ReportArtifactExporter,
    registered_artifact_exporters,
    registered_report_artifact_exporters,
)
from dp_lookup.application.image_artifacts import MapImageArtifactExporter


def export_vector_artifacts(
    context: ArtifactContext,
    dependencies: LookupDependencies,
    warnings: List[str],
) -> None:
    """Export synchronous bundle artifacts through their common plug-in contract."""
    seen_keys = set()
    for exporter in registered_artifact_exporters(dependencies):
        if exporter.manifest_key in seen_keys:
            warnings.append(
                f"Artifact exporter '{exporter.name}' reused manifest key '{exporter.manifest_key}' and was skipped"
            )
            continue
        seen_keys.add(exporter.manifest_key)
        output_path = run_artifact_result(
            exporter.name,
            warnings,
            _export_bundle_artifact,
            exporter,
            context,
        )
        if output_path is not None:
            context.artifact_outputs[exporter.manifest_key] = output_path


def _export_bundle_artifact(exporter: ArtifactExporter, context: ArtifactContext) -> str:
    """Export and verify that a plug-in produced a cacheable bundle artifact."""
    output_path = _canonical_path(exporter.export(context))
    bundle_folder = _canonical_path(context.paths.bundle_folder)
    if os.path.commonpath((bundle_folder, output_path)) != bundle_folder:
        raise ValueError("exported artifact must be inside the lookup bundle")
    _require_nonempty_file(output_path)
    return output_path


async def render_report_artifacts(
    context: ArtifactContext,
    fetched: MapFetchContext,
    dependencies: LookupDependencies,
    warnings: List[str],
) -> None:
    """Build visual assets, then hand them to typed report-stage exporters."""
    maps = await MapImageArtifactExporter(dependencies).export(context, fetched, warnings)
    report_context = ReportArtifactContext(context, maps)
    seen_keys = set()
    for exporter in registered_report_artifact_exporters(dependencies):
        if exporter.manifest_key in seen_keys:
            warnings.append(
                f"Artifact exporter '{exporter.name}' reused manifest key '{exporter.manifest_key}' and was skipped"
            )
            continue
        seen_keys.add(exporter.manifest_key)
        await _export_report_artifact(exporter, report_context, warnings)


async def _export_report_artifact(
    exporter: ReportArtifactExporter,
    context: ReportArtifactContext,
    warnings: List[str],
) -> None:
    """Run a costly report exporter in a worker and retain failure isolation."""
    output_path = await _run_report_exporter(exporter, context, warnings)
    if output_path is not None:
        run_artifact(exporter.name, warnings, _require_nonempty_file, output_path)


async def _run_report_exporter(
    exporter: ReportArtifactExporter,
    context: ReportArtifactContext,
    warnings: List[str],
) -> Optional[str]:
    completed: List[str] = []

    def export() -> None:
        completed.append(_canonical_path(exporter.export(context)))

    if not await run_artifact_in_thread(exporter.name, warnings, export):
        return None
    return completed[0]


def _canonical_path(path: str) -> str:
    return os.path.realpath(os.path.abspath(os.path.expanduser(os.fspath(path))))


def _require_nonempty_file(path: str) -> None:
    if not os.path.isfile(path) or os.path.getsize(path) <= 0:
        raise ValueError("exported artifact is missing or empty")
