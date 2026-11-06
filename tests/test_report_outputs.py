"""Regressions for full planning notes, satellite framing and neighbour labels."""

import asyncio
import io
from dataclasses import replace

import pytest
from PIL import Image
from reportlab.platypus import Image as ReportImage
from reportlab.platypus import Paragraph, SimpleDocTemplate, Table

from dp_lookup.application.dependencies import DEFAULT_DEPENDENCIES
from dp_lookup.application.ingestion import build_parcel_context
from dp_lookup.application.telemetry import RunDiagnostics
from dp_lookup.application.visual_fetch import start_visual_fetch
from dp_lookup.core.geometry import tile_to_latlon
from dp_lookup.exporters.pdf_renderer import build_pdf_doc


def _paragraphs(story):
    for item in story:
        if isinstance(item, Paragraph):
            yield item
        elif isinstance(item, Table):
            for row in item._cellvalues:
                yield from _paragraphs(row)
        elif isinstance(item, (list, tuple)):
            yield from _paragraphs(item)


@pytest.mark.parametrize("satellite_size", [(768, 768), (900, 600), (600, 900)])
def test_pdf_preserves_full_note_source_link_image_proportions_and_area_basis(tmp_path, monkeypatch, satellite_size):
    map_path = tmp_path / "map.png"
    satellite_path = tmp_path / "satellite.png"
    Image.new("RGB", (100, 100)).save(map_path)
    Image.new("RGB", satellite_size).save(satellite_path)
    qr = io.BytesIO(map_path.read_bytes())
    captured = []
    captured_links = []
    original_build = SimpleDocTemplate.build

    def capture_build(doc, story, *args, **kwargs):
        captured.extend(story)
        for paragraph in _paragraphs(story):
            for fragment in paragraph.frags:
                captured_links.extend(getattr(fragment, "link", ()))
        return original_build(doc, story, *args, **kwargs)

    monkeypatch.setattr(SimpleDocTemplate, "build", capture_build)
    note = (
        "Existing Amenity of Municipal Hospital (EH1.2) shown on plot bearing CS no 1605 "
        "of Byculla Division is deleted and shown in adjoining predominant Residential Zone."
    )
    document = 'https://example.test/notification.pdf?name="hospital"&version=2'
    output = tmp_path / "report.pdf"
    build_pdf_doc(
        str(output),
        status_badge="MODIFIED",
        status_summary="Source notification applies",
        village="BYCULLA",
        attrs={"WARD": "E", "TYPE": "CTS", "AREA_APP_SQ_MTRS": 1877.87},
        cts_number="1605",
        zone="R",
        des_desc="Municipal Hospital",
        des_code="EH1.2",
        mod_approval="MCP/7526",
        mod_label=note,
        modification_document=document,
        crz_buffer_flag="NO",
        metro_buffer_flag="YES",
        road_name="Test road",
        road_width="18 M",
        dp_snapshot_path=str(map_path),
        qr_bytes=qr,
        map_link="https://example.test/map",
        sat_snapshot_path=str(satellite_path),
        neighbors=[
            {"cts_no": "1", "village": "BYCULLA", "area_sqm": "20310.61", "area_source": "Calculated boundary area"},
            {"cts_no": "2", "village": "BYCULLA", "area_sqm": "100", "area_source": "Recorded plot area"},
        ],
    )
    paragraphs = list(_paragraphs(captured))
    text = "\n".join(item.getPlainText() for item in paragraphs)
    assert note in text
    assert "Open source notification" in text
    assert any(target == document for _, target in captured_links)
    assert "Calculated nearby pieces" in text
    assert "MCGM recorded area" in text
    assert "A full CTS lookup may include additional pieces and a larger area." in text
    satellite = next(item for item in captured if isinstance(item, ReportImage))
    assert satellite.drawWidth / satellite.drawHeight == pytest.approx(satellite_size[0] / satellite_size[1])
    assert satellite.drawWidth <= 540
    assert satellite.drawHeight <= 340
    assert output.read_bytes().count(b"/Type /Page\n") == 2


@pytest.mark.parametrize("parts", [[(0, 10)], [(0, 20), (250, 280)], [(0, 5000)]])
def test_satellite_window_covers_all_plot_parts_with_only_nine_tiles(parts):
    rings = [
        [[8106500 + x, 2151700 + y] for x, y in [(left, 0), (right, 0), (right, 100), (left, 100), (left, 0)]]
        for left, right in parts
    ]
    parcel, _ = build_parcel_context(
        {"attributes": {"WARD": "G/S", "TYPE": "CTS", "AREA_APP_SQ_MTRS": 100}, "geometry": {"rings": rings}},
        "WORLI",
        "733",
    )
    calls = []

    class Client:
        async def get(self, *_args, **_kwargs):
            return object()

    async def tile_fetcher(_client, zoom, y, x):
        calls.append((zoom, y, x))
        return None

    async def run():
        diagnostics = RunDiagnostics()
        session = start_visual_fetch(
            Client(), parcel, replace(DEFAULT_DEPENDENCIES, tile_fetcher=tile_fetcher), diagnostics
        )
        return await session.resolve(diagnostics)

    fetched = asyncio.run(run())
    top, left = tile_to_latlon(fetched.tile_x - 1, fetched.tile_y - 1, fetched.zoom)
    bottom, right = tile_to_latlon(fetched.tile_x + 2, fetched.tile_y + 2, fetched.zoom)
    lon_padding = (right - left) / 32
    lat_padding = (top - bottom) / 32
    for ring in parcel.wgs_rings:
        for lon, lat in ring:
            assert left + lon_padding <= lon <= right - lon_padding
            assert bottom + lat_padding <= lat <= top - lat_padding
    assert len(calls) == len(set(calls)) == 9
    assert len(fetched.satellite_coordinates) == 9
    if parts[-1][1] == 5000:
        assert fetched.zoom < 18
