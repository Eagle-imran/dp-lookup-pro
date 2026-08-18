"""End-to-end offline contract tests for the ArcGIS ingestion pipeline."""

from __future__ import annotations

import asyncio
import io
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from PIL import Image

from dp_lookup.application import lookup_service as orchestrator
from dp_lookup.application.contracts import ArtifactContext
from dp_lookup.application.dependencies import DEFAULT_DEPENDENCIES
from dp_lookup.core.models import ExportData
from dp_lookup.planning_evidence import EvidenceMode, PlanningEvidenceReport


class FakeResponse:
    def __init__(
        self,
        payload: Optional[Dict[str, Any]] = None,
        *,
        content: bytes = b"",
        content_type: str = "application/json",
        status_code: int = 200,
    ):
        self._payload = payload
        self.content = content
        self.status_code = status_code
        self.headers = {"content-type": content_type}

    def json(self) -> Dict[str, Any]:
        if self._payload is None:
            raise ValueError("not JSON")
        return self._payload


def _png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (256, 256), "white").save(output, "PNG")
    return output.getvalue()


class FakeArcGISClient:
    def __init__(self, *, include_zone: bool = True, fail_map: bool = False):
        self.include_zone = include_zone
        self.fail_map = fail_map
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, *, params=None, timeout=None):
        self.calls.append(("GET", url, params))
        if url.endswith("/13/query"):
            return FakeResponse(
                {
                    "features": [
                        {
                            "attributes": {
                                "WARD": "G/S",
                                "TYPE": "CTS",
                                "VILLAGE": "WORLI",
                                "CTS_CS_NO": "733",
                                "AREA_APP_SQ_MTRS": 100.0,
                                "SHAPE.AREA": 100.0,
                            },
                            "geometry": {
                                "rings": [
                                    [
                                        [8106500.0, 2151700.0],
                                        [8106510.0, 2151700.0],
                                        [8106510.0, 2151710.0],
                                        [8106500.0, 2151710.0],
                                        [8106500.0, 2151700.0],
                                    ]
                                ]
                            },
                        }
                    ],
                }
            )
        if url.endswith("/export"):
            if self.fail_map:
                raise httpx.ReadTimeout("map timeout")
            return FakeResponse(content=_png_bytes(), content_type="image/png")
        if "/tile/" in url:
            return FakeResponse(content=_png_bytes(), content_type="image/png")
        raise AssertionError(f"unexpected GET {url}")

    async def post(self, url, *, data=None):
        self.calls.append(("POST", url, data))
        if url.endswith("/identify"):
            layers = (data or {}).get("layers", "")
            if layers == "visible:13":
                return FakeResponse({"results": []})
            if layers.startswith("visible:193"):
                return FakeResponse({"results": []})
            results = []
            if self.include_zone:
                results.append({"layerId": 0, "attributes": {"Zone_Code2": "R"}})
            return FakeResponse({"results": results})

        layer_id = int(url.rsplit("/", 2)[-2])
        features = []
        if layer_id == 0 and self.include_zone:
            features = [
                {
                    "attributes": {"ZONE_CODE2": "R"},
                    "geometry": {
                        "rings": [
                            [
                                [8106490.0, 2151690.0],
                                [8106520.0, 2151690.0],
                                [8106520.0, 2151720.0],
                                [8106490.0, 2151720.0],
                                [8106490.0, 2151690.0],
                            ]
                        ]
                    },
                }
            ]
        return FakeResponse({"features": features})


def _stub_dependencies(client_factory):
    def vector_writer(_rings, _props, path, **_kwargs):
        assert isinstance(_props, ExportData)
        Path(path).write_text("artifact", encoding="utf-8")

    def pdf_writer(path, *_args, **_kwargs):
        Path(path).write_bytes(b"%PDF-placeholder")

    def excel_writer(*_args, **kwargs):
        Path(kwargs["register_path"]).write_text("register", encoding="utf-8")

    return replace(
        DEFAULT_DEPENDENCIES,
        client_factory=client_factory,
        geojson_writer=vector_writer,
        dxf_writer=vector_writer,
        kml_writer=vector_writer,
        html_writer=vector_writer,
        pdf_writer=pdf_writer,
        excel_writer=excel_writer,
    )


class SvgArtifactExporter:
    name = "SVG massing handoff"
    manifest_key = "massing_svg"

    def export(self, context: ArtifactContext) -> str:
        path = Path(context.paths.bundle_folder) / "massing-handoff.svg"
        path.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
        return str(path)


class EscapingArtifactExporter:
    name = "unsafe external artifact"
    manifest_key = "unsafe_external"

    def export(self, context: ArtifactContext) -> str:
        path = Path(context.paths.bundle_folder).parent / "outside-bundle.svg"
        path.write_text("<svg/>", encoding="utf-8")
        return str(path)


def test_complete_lookup_preserves_arcgis_contract(tmp_path):
    client = FakeArcGISClient()
    client_options = {}

    def client_factory(timeout_seconds, verify_tls=True):
        client_options.update(timeout_seconds=timeout_seconds, verify_tls=verify_tls)
        return client

    dependencies = _stub_dependencies(client_factory)
    snapshots = []

    result = asyncio.run(
        orchestrator.lookup_plot_pro(
            "WORLI",
            "733",
            str(tmp_path),
            use_cache=False,
            on_data=snapshots.append,
            dependencies=dependencies,
        )
    )

    assert "error" not in result
    assert result["planning_remarks"]["zone"] == "R"
    assert result["metadata"]["complete"] is True
    assert result["metadata"]["application_version"] == "3.14.0"
    assert result["metadata"]["result_schema_version"] == 1
    assert result["metadata"]["evidence"]["parcel"]["state"] == "confirmed"
    assert result["metadata"]["evidence"]["zoning"]["layer_ids"] == [0]
    assert result["spatial_cluster"]["adjacency_method"] == "probe"
    assert snapshots and snapshots[0]["metadata"]["documents_pending"] is True
    assert client_options == {"timeout_seconds": 20.0, "verify_tls": True}

    queried_layers = {
        int(url.rsplit("/", 2)[-2]) for method, url, _ in client.calls if method == "POST" and url.endswith("/query")
    }
    assert queried_layers == {0, 14, 46, 47, 192, 1264, 1548, 1550}
    assert any(url.endswith("/13/query") for method, url, _ in client.calls if method == "GET")
    assert all(
        Path(path).exists()
        for key, path in result["export_files"].items()
        if key not in ("bundle_folder", "master_excel_register")
    )


def test_registered_artifact_plugin_requires_no_orchestrator_change(tmp_path):
    dependencies = replace(
        _stub_dependencies(lambda timeout_seconds, verify_tls=True: FakeArcGISClient()),
        artifact_exporters=(SvgArtifactExporter(),),
    )

    result = asyncio.run(
        orchestrator.lookup_plot_pro(
            "WORLI",
            "733",
            str(tmp_path),
            use_cache=False,
            dependencies=dependencies,
        )
    )

    plugin_path = Path(result["export_files"]["massing_svg"])
    assert plugin_path.is_file()
    assert plugin_path.read_text(encoding="utf-8").startswith("<svg")


def test_registered_artifact_must_stay_inside_bundle(tmp_path):
    dependencies = replace(
        _stub_dependencies(lambda timeout_seconds, verify_tls=True: FakeArcGISClient()),
        artifact_exporters=(EscapingArtifactExporter(),),
    )

    result = asyncio.run(
        orchestrator.lookup_plot_pro(
            "WORLI",
            "733",
            str(tmp_path),
            use_cache=False,
            dependencies=dependencies,
        )
    )

    assert "unsafe_external" not in result["export_files"]
    assert any("must be inside the lookup bundle" in warning for warning in result["metadata"]["warnings"])


def test_missing_zoning_evidence_never_becomes_clear(tmp_path):
    dependencies = _stub_dependencies(
        lambda timeout_seconds, verify_tls=True: FakeArcGISClient(include_zone=False),
    )

    result = asyncio.run(
        orchestrator.lookup_plot_pro(
            "WORLI",
            "733",
            str(tmp_path),
            use_cache=False,
            dependencies=dependencies,
        )
    )

    assert "no usable zoning evidence" in result["error"]
    assert "planning_remarks" not in result


def test_optional_map_timeout_is_a_warning_not_a_traceback(tmp_path):
    dependencies = _stub_dependencies(
        lambda timeout_seconds, verify_tls=True: FakeArcGISClient(fail_map=True),
    )

    result = asyncio.run(
        orchestrator.lookup_plot_pro(
            "WORLI",
            "733",
            str(tmp_path),
            use_cache=False,
            dependencies=dependencies,
        )
    )

    assert "error" not in result
    assert result["metadata"]["complete"] is False
    assert any("DP base map" in warning for warning in result["metadata"]["warnings"])


def test_spatial_query_failure_uses_identify_but_never_claims_complete(tmp_path):
    async def fail_spatial(_client, _rings):
        raise RuntimeError("spatial query unavailable")

    dependencies = replace(
        _stub_dependencies(lambda timeout_seconds, verify_tls=True: FakeArcGISClient()),
        spatial_planning_query=fail_spatial,
    )
    result = asyncio.run(
        orchestrator.lookup_plot_pro(
            "WORLI",
            "733",
            str(tmp_path),
            use_cache=False,
            dependencies=dependencies,
        )
    )

    assert "error" not in result
    assert result["planning_remarks"]["zone"] == "R"
    assert result["metadata"]["complete"] is False
    assert result["metadata"]["evidence"]["planning_constraints"]["state"] == "unknown"
    assert any("point-identify fallback" in warning for warning in result["metadata"]["warnings"])
    assert not (tmp_path / ".cache_store.json").exists()


def test_renderer_failure_is_isolated_and_suppresses_cache(tmp_path):
    def fail_renderer(*_args, **_kwargs):
        raise RuntimeError("renderer failed")

    dependencies = replace(
        _stub_dependencies(lambda timeout_seconds, verify_tls=True: FakeArcGISClient()),
        dp_map_renderer=fail_renderer,
    )
    result = asyncio.run(
        orchestrator.lookup_plot_pro("WORLI", "733", str(tmp_path), dependencies=dependencies)
    )
    assert "error" not in result
    assert result["metadata"]["complete"] is False
    assert any("DP map rendering" in warning for warning in result["metadata"]["warnings"])
    assert Path(result["export_files"]["hd_dp_map"]).exists()
    assert not (tmp_path / ".cache_store.json").exists()


def test_shadow_evidence_is_nested_and_does_not_change_core_completeness(tmp_path):
    calls = []

    async def evidence_analyzer(_client, _rings, village, mode):
        calls.append((village, mode))
        return PlanningEvidenceReport(
            mode=EvidenceMode.SHADOW,
            retrieved_at="2026-08-18T12:00:00+00:00",
            complete=False,
            warnings=("optional layer unavailable",),
        )

    dependencies = replace(
        _stub_dependencies(lambda timeout_seconds, verify_tls=True: FakeArcGISClient()),
        planning_evidence_analyzer=evidence_analyzer,
        planning_evidence_mode=EvidenceMode.SHADOW,
    )
    result = asyncio.run(orchestrator.lookup_plot_pro("WORLI", "733", str(tmp_path), dependencies=dependencies))

    assert calls == [("WORLI", EvidenceMode.SHADOW)]
    assert result["metadata"]["complete"] is True
    assert result["metadata"]["warnings"] == []
    evidence = result["metadata"]["evidence"]["planning_due_diligence"]
    assert evidence["mode"] == "shadow"
    assert evidence["complete"] is False
    assert not (tmp_path / ".cache_store.json").exists()


def test_standard_evidence_failure_is_visible_but_does_not_break_core_lookup(tmp_path):
    async def fail_evidence(_client, _rings, _village, _mode):
        raise RuntimeError("optional evidence failed")

    dependencies = replace(
        _stub_dependencies(lambda timeout_seconds, verify_tls=True: FakeArcGISClient()),
        planning_evidence_analyzer=fail_evidence,
        planning_evidence_mode=EvidenceMode.STANDARD,
    )
    result = asyncio.run(
        orchestrator.lookup_plot_pro("WORLI", "733", str(tmp_path), use_cache=False, dependencies=dependencies)
    )

    assert result["metadata"]["complete"] is True
    assert any("Extended planning evidence failed" in note for note in result["metadata"]["notes"])
    evidence = result["metadata"]["evidence"]["planning_due_diligence"]
    assert evidence["complete"] is False
    assert "optional evidence failed" in evidence["warnings"][0]
