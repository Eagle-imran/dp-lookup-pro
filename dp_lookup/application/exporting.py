"""Typed artifact plug-in boundary and adapters for legacy writer functions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Protocol, Sequence, Tuple

from dp_lookup.application.contracts import ArtifactContext
from dp_lookup.core.models import ExportData

if TYPE_CHECKING:
    from dp_lookup.application.dependencies import LookupDependencies

Rings = List[List[List[float]]]
RoadGeometry = Sequence[Sequence[Sequence[float]]]


class SimpleVectorWriter(Protocol):
    def __call__(self, wgs_rings: Rings, properties: ExportData, output_path: str) -> None: ...


class RichVectorWriter(Protocol):
    def __call__(
        self,
        wgs_rings: Rings,
        properties: ExportData,
        output_path: str,
        *,
        neighbors: List[Dict[str, Any]],
        roads: RoadGeometry,
        reservations: List[Dict[str, Any]],
        designations: List[Dict[str, Any]],
    ) -> None: ...


class ArtifactExporter(Protocol):
    """Extension point for a synchronous, independently-failable artifact."""

    @property
    def name(self) -> str: ...

    @property
    def manifest_key(self) -> str: ...

    def export(self, context: ArtifactContext) -> str:
        """Write one artifact and return its canonical path."""
        ...


@dataclass(frozen=True)
class SimpleVectorExporter:
    name: str
    manifest_key: str
    path_attribute: str
    writer: SimpleVectorWriter

    def export(self, context: ArtifactContext) -> str:
        output_path = str(getattr(context.paths, self.path_attribute))
        self.writer(context.parcel.wgs_rings, context.export_data, output_path)
        return output_path


@dataclass(frozen=True)
class RichVectorExporter:
    name: str
    manifest_key: str
    path_attribute: str
    writer: RichVectorWriter

    def export(self, context: ArtifactContext) -> str:
        output_path = str(getattr(context.paths, self.path_attribute))
        self.writer(
            context.parcel.wgs_rings,
            context.export_data,
            output_path,
            neighbors=context.neighbours.plots,
            roads=context.nearest_roads,
            reservations=context.planning.reservations,
            designations=context.planning.designations,
        )
        return output_path


def registered_artifact_exporters(dependencies: LookupDependencies) -> Tuple[ArtifactExporter, ...]:
    """Resolve built-ins plus caller-supplied plug-ins without editing orchestration."""
    built_ins: Tuple[ArtifactExporter, ...] = (
        SimpleVectorExporter("GeoJSON", "autocad_geojson", "geojson", dependencies.geojson_writer),
        RichVectorExporter("DXF", "autocad_dxf", "dxf", dependencies.dxf_writer),
        SimpleVectorExporter("KML", "google_earth_kml", "kml", dependencies.kml_writer),
        RichVectorExporter("HTML map", "interactive_html_map", "html_map", dependencies.html_writer),
    )
    return built_ins + tuple(dependencies.artifact_exporters)
