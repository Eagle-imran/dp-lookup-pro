"""
Offline regression tests for dp-lookup-pro.

None of these touch the network. They cover the pure logic that had no
protection before: projection maths, tile arithmetic, input validation,
XML/markup escaping, cache expiry, ArcGIS error-body detection, and the
three vector exporters.

Run:  uv run pytest -q
"""
import json
import math
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cts_dp_lookup_pro as dp


# --------------------------------------------------------------------------
# Projection and tile maths
# --------------------------------------------------------------------------

def test_utm43n_matches_known_mumbai_point():
    """Mumbai sits in UTM zone 43N; easting must land west of the 500 km meridian."""
    easting, northing = dp.wgs84_to_utm43n(72.8776, 19.0760)
    assert 200_000 < easting < 500_000
    assert 2_000_000 < northing < 2_200_000


def test_utm43n_easting_grows_with_longitude():
    e1, _ = dp.wgs84_to_utm43n(72.80, 19.00)
    e2, _ = dp.wgs84_to_utm43n(72.90, 19.00)
    assert e2 > e1


def test_utm43n_northing_grows_with_latitude():
    _, n1 = dp.wgs84_to_utm43n(72.85, 18.90)
    _, n2 = dp.wgs84_to_utm43n(72.85, 19.10)
    assert n2 > n1


@pytest.mark.parametrize("lat,lon", [(19.0760, 72.8776), (18.9724, 72.8226), (19.1016, 72.8841)])
def test_tile_roundtrip_lands_in_same_tile(lat, lon):
    """tile -> latlon -> tile must be stable, or the satellite overlay misaligns."""
    zoom = 18
    x, y = dp.latlon_to_tile(lat, lon, zoom)
    back_lat, back_lon = dp.tile_to_latlon(x, y, zoom)
    x2, y2 = dp.latlon_to_tile(back_lat, back_lon, zoom)
    assert (x, y) == (x2, y2)


def test_tile_to_latlon_is_tile_top_left():
    zoom = 18
    lat, lon = dp.tile_to_latlon(*dp.latlon_to_tile(19.0, 72.8, zoom), zoom)
    assert lat >= 19.0 - 0.01 and lon <= 72.8


# --------------------------------------------------------------------------
# Input validation  (regression: sql-injection-where-clause)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("value", [
    "BANDRA-A", "MALABAR HILL", "KURLA - 1", "BHANDUP-E",
    "WORLI", "16/738", "748A", "1605",
])
def test_real_mcgm_values_are_accepted(value):
    assert dp.sanitize_query_value(value, dp._VILLAGE_RE, "village", 64) == value


@pytest.mark.parametrize("value", [
    "1' OR '1'='1",
    "WORLI'--",
    "'; DROP TABLE x; --",
    "A" * 100,
    "",
    "   ",
    "bad\nvalue",
])
def test_injection_and_junk_are_rejected(value):
    with pytest.raises(ValueError):
        dp.sanitize_query_value(value, dp._VILLAGE_RE, "village", 64)


def test_single_quotes_never_reach_the_where_clause():
    """The whitelist rejects quotes outright; doubling is only defence in depth."""
    with pytest.raises(ValueError):
        dp.sanitize_query_value("A'B", dp._VILLAGE_RE, "village", 64)


def test_whitespace_is_trimmed_not_rejected():
    assert dp.sanitize_query_value("  WORLI  ", dp._VILLAGE_RE, "village", 64) == "WORLI"


# --------------------------------------------------------------------------
# ArcGIS error-body detection  (regression: http-200-with-error-body-swallowed)
# --------------------------------------------------------------------------

class FakeResp:
    def __init__(self, status=200, payload=None, boom=False):
        self.status_code = status
        self._payload = payload
        self._boom = boom

    def json(self):
        if self._boom:
            raise ValueError("not json")
        return self._payload


def test_usable_json_rejects_arcgis_error_body_despite_http_200():
    resp = FakeResp(200, {"error": {"code": 400, "message": "", "details": []}})
    assert dp.usable_json(resp) is None


def test_usable_json_accepts_real_payload():
    resp = FakeResp(200, {"results": [{"layerId": 14}]})
    assert dp.usable_json(resp) == {"results": [{"layerId": 14}]}


def test_usable_json_rejects_non_200_exception_and_bad_json():
    assert dp.usable_json(FakeResp(500, {"results": []})) is None
    assert dp.usable_json(RuntimeError("timeout")) is None
    assert dp.usable_json(FakeResp(200, None, boom=True)) is None
    assert dp.usable_json(None) is None


def test_empty_results_is_distinguishable_from_failure():
    """A genuine no-match must survive; only failures return None."""
    assert dp.usable_json(FakeResp(200, {"results": []})) == {"results": []}


# --------------------------------------------------------------------------
# Escaping  (regression: kml-no-xml-escaping, reportlab markup injection)
# --------------------------------------------------------------------------

def test_esc_handles_xml_metacharacters():
    assert dp._esc("A & B") == "A &amp; B"
    assert dp._esc("<tag>") == "&lt;tag&gt;"
    assert dp._esc(None) == ""
    assert dp._esc(1877.87) == "1877.87"


def test_kml_with_ampersand_village_is_well_formed(tmp_path):
    import xml.etree.ElementTree as ET
    out = tmp_path / "x.kml"
    dp.export_kml(
        [[[72.8, 19.0], [72.81, 19.0], [72.81, 19.01], [72.8, 19.0]]],
        {"cts_no": "7 & 8", "village": "A<B>", "ward": "G/S", "zone": "R",
         "area_sqm": 100, "status_badge": "CLEAR", "crz_buffer_flag": "NO",
         "metro_buffer_flag": "NO", "abutting_road": "R & R", "road_width": "9 M"},
        str(out),
    )
    ET.parse(str(out))  # raises if the escaping is wrong


# --------------------------------------------------------------------------
# Cache behaviour  (regression: cache-no-expiry, cache-path-cwd-relative)
# --------------------------------------------------------------------------

def test_cache_path_follows_output_dir(tmp_path):
    assert dp.cache_path_for(str(tmp_path)) == os.path.join(str(tmp_path), dp.CACHE_FILENAME)


def test_cache_roundtrip_then_expiry(tmp_path):
    d = str(tmp_path)
    dp._STORES.clear()
    dp.write_cache_entry(d, "WORLI:947", _entry_with_files(tmp_path))
    assert dp.read_cache_entry(d, "WORLI:947", 3600) is not None
    # ttl of 0 means anything with a positive age is stale
    time.sleep(0.01)
    assert dp.read_cache_entry(d, "WORLI:947", 0) is None


def test_legacy_untimestamped_entries_are_treated_as_expired(tmp_path):
    """Pre-fix entries hold the old CRZ answers and must never be served."""
    d = str(tmp_path)
    dp._STORES.clear()
    with open(dp.cache_path_for(d), "w", encoding="utf-8") as f:
        json.dump({"WORLI:947": {"planning_remarks": {"zone": "R"}}}, f)
    assert dp.read_cache_entry(d, "WORLI:947", 3600) is None


def test_negative_ttl_disables_expiry(tmp_path):
    d = str(tmp_path)
    dp._STORES.clear()
    dp.write_cache_entry(d, "K", _entry_with_files(tmp_path))
    got = dp.read_cache_entry(d, "K", -1)
    assert got is not None
    assert got["metadata"]["cache_expires_in_days"] is None


def _entry_with_files(tmp_path, names=("a.pdf", "b.png")):
    """Build a cached result whose promised files really exist."""
    files = {}
    for i, n in enumerate(names):
        fp = tmp_path / n
        fp.write_text("x")
        files[f"f{i}"] = str(fp)
    files["master_excel_register"] = str(tmp_path / "never-written.xlsx")
    return {"metadata": {}, "export_files": files}


def test_default_ttl_is_thirty_days():
    assert dp.DEFAULT_CACHE_TTL_SECONDS == 30 * 24 * 60 * 60


def test_cache_hit_requires_files_to_exist(tmp_path):
    """Regression: a hit used to return paths to deleted files and report success."""
    d = str(tmp_path)
    dp._STORES.clear()
    result = _entry_with_files(tmp_path)
    dp.write_cache_entry(d, "K", result)
    assert dp.read_cache_entry(d, "K", 3600) is not None

    os.remove(result["export_files"]["f0"])
    assert dp.read_cache_entry(d, "K", 3600) is None, "deleted bundle must invalidate the entry"


def test_missing_excel_register_does_not_invalidate(tmp_path):
    """The register is shared and regenerated; its absence must not nuke the entry."""
    d = str(tmp_path)
    dp._STORES.clear()
    dp.write_cache_entry(d, "K", _entry_with_files(tmp_path))
    assert dp.read_cache_entry(d, "K", 3600) is not None


def test_bundle_is_intact_rejects_malformed_result():
    assert dp.bundle_is_intact({}) is False
    assert dp.bundle_is_intact({"export_files": "nope"}) is False


def test_cache_hit_reports_its_age(tmp_path):
    """Staleness must never be silent - the caller sees how old the answer is."""
    d = str(tmp_path)
    dp._STORES.clear()
    dp.write_cache_entry(d, "K", _entry_with_files(tmp_path))
    got = dp.read_cache_entry(d, "K", dp.DEFAULT_CACHE_TTL_SECONDS)
    meta = got["metadata"]
    assert "cached_at" in meta
    assert meta["cache_age_days"] >= 0
    assert 29 <= meta["cache_expires_in_days"] <= 30


def test_reading_cache_does_not_mutate_the_store(tmp_path):
    """Age fields are added to the returned copy, not written back to disk."""
    d = str(tmp_path)
    dp._STORES.clear()
    dp.write_cache_entry(d, "K", _entry_with_files(tmp_path))
    dp.read_cache_entry(d, "K", 3600)
    stored = dp.load_disk_cache(d)["K"]["result"]
    assert "cache_age_days" not in stored.get("metadata", {})


def test_cache_survives_corrupt_store(tmp_path):
    d = str(tmp_path)
    dp._STORES.clear()
    with open(dp.cache_path_for(d), "w", encoding="utf-8") as f:
        f.write("{not json")
    assert dp.read_cache_entry(d, "anything", 3600) is None


# --------------------------------------------------------------------------
# Vector exporters
# --------------------------------------------------------------------------

RING = [[[72.8200, 18.9700], [72.8210, 18.9700], [72.8210, 18.9710], [72.8200, 18.9710], [72.8200, 18.9700]]]
PROPS = {
    "cts_no": "947", "village": "WORLI", "ward": "G/S", "zone": "R",
    "area_sqm": 462.28, "status_badge": "CLEAR", "crz_buffer_flag": "YES (CRZ II)",
    "metro_buffer_flag": "NO", "abutting_road": "B G KHER", "road_width": "18.30 M",
}


def test_geojson_is_valid_and_crs84(tmp_path):
    out = tmp_path / "x.geojson"
    dp.export_geojson(RING, PROPS, str(out))
    data = json.loads(out.read_text())
    assert data["type"] == "FeatureCollection"
    assert data["crs"]["properties"]["name"] == "urn:ogc:def:crs:OGC:1.3:CRS84"
    assert data["features"][0]["geometry"]["type"] == "Polygon"


def test_dxf_written_with_expected_layers(tmp_path):
    ezdxf = pytest.importorskip("ezdxf")
    out = tmp_path / "x.dxf"
    dp.export_dxf(RING, PROPS, str(out), neighbors=[])
    doc = ezdxf.readfile(str(out))
    names = {layer.dxf.name for layer in doc.layers}
    for expected in ("C-PLOT-BDY", "C-ANNO-DIMS", "C-TITLE-BLOCK"):
        assert expected in names


def test_dxf_geometry_is_metric_and_centred_on_origin(tmp_path):
    ezdxf = pytest.importorskip("ezdxf")
    out = tmp_path / "x.dxf"
    dp.export_dxf(RING, PROPS, str(out), neighbors=[])
    doc = ezdxf.readfile(str(out))
    pts = []
    for e in doc.modelspace().query("LWPOLYLINE[layer=='C-PLOT-BDY']"):
        pts.extend([(p[0], p[1]) for p in e.get_points("xy")])
    assert pts, "no plot boundary polyline written"
    # ~105 m x ~111 m parcel, centred on a local origin
    assert max(abs(x) for x, _ in pts) < 200
    assert max(abs(y) for _, y in pts) < 200


def _dist_to_boundary(pt, poly):
    best = 1e9
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        l2 = dx * dx + dy * dy
        if l2 == 0:
            continue
        t = max(0.0, min(1.0, ((pt[0] - a[0]) * dx + (pt[1] - a[1]) * dy) / l2))
        best = min(best, math.hypot(pt[0] - (a[0] + t * dx), pt[1] - (a[1] + t * dy)))
    return best


SQUARE = [(0, 0), (100, 0), (100, 100), (0, 100)]
# concave L - the shape class that broke the hand-rolled miter offset
L_SHAPE = [(0, 0), (60, 0), (60, 20), (20, 20), (20, 60), (0, 60)]


def test_setback_offset_is_exact_on_a_square():
    rings = dp.offset_polygon_inward(SQUARE, 10)
    assert len(rings) == 1
    assert abs(abs(dp.polygon_signed_area(rings[0])) - 6400.0) < 0.01


@pytest.mark.parametrize("poly", [SQUARE, L_SHAPE])
@pytest.mark.parametrize("distance", [3.0, 6.0])
def test_setback_is_a_true_parallel_offset(poly, distance):
    """
    The two properties an architect depends on, checked along the whole line
    rather than at vertices only:

      1. No part of the setback line is closer than `distance` to the boundary
         (it never encroaches).
      2. It actually touches `distance` somewhere (it is not over-conservative,
         which would silently shrink the buildable envelope).

    Vertices at reflex corners sit further out than `distance` by design - that
    is what a mitre join does - so a per-vertex equality check is the wrong test.
    """
    rings = dp.offset_polygon_inward(poly, distance)
    assert rings, "expected a viable setback"

    sampled = []
    for ring in rings:
        for i in range(len(ring)):
            a, b = ring[i], ring[(i + 1) % len(ring)]
            for step in range(21):  # sample along each edge, not just the ends
                t = step / 20.0
                sampled.append(_dist_to_boundary(
                    (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t), poly))

    assert min(sampled) >= distance - 0.02, "setback encroaches inside the required distance"
    assert min(sampled) <= distance + 0.02, "setback is further in than required"


def test_setback_is_winding_independent():
    a = dp.offset_polygon_inward(SQUARE, 10)
    b = dp.offset_polygon_inward(SQUARE[::-1], 10)
    assert abs(abs(dp.polygon_signed_area(a[0])) - abs(dp.polygon_signed_area(b[0]))) < 0.01


def test_setback_omitted_when_plot_cannot_sustain_it():
    """Better to draw nothing than a line an architect would build to."""
    assert dp.offset_polygon_inward([(0, 0), (4, 0), (4, 4), (0, 4)], 6.0) == []
    assert dp.offset_polygon_inward([(0, 0), (1, 0), (1, 1)], 3.0) == []


def test_setback_handles_duplicate_closing_vertex():
    closed = SQUARE + [SQUARE[0]]
    assert dp.offset_polygon_inward(closed, 10)


def test_dxf_has_no_empty_layers_and_carries_a_legend(tmp_path):
    """A declared-but-empty layer misleads whoever opens the drawing."""
    ezdxf = pytest.importorskip("ezdxf")
    out = tmp_path / "x.dxf"
    ring = [[[72.8200, 18.9700], [72.8215, 18.9700], [72.8215, 18.9715],
             [72.8200, 18.9715], [72.8200, 18.9700]]]
    props = dict(PROPS, crz_buffer_flag="YES (CRZ II)", metro_buffer_flag="YES",
                 area_source="approved (MCGM AREA_APP_SQ_MTRS)")
    roads = [[[72.8195, 18.9698], [72.8220, 18.9698]]]
    neighbours = [{"cts_no": "948", "rings": [[[72.8216, 18.9700], [72.8225, 18.9700],
                                               [72.8225, 18.9712], [72.8216, 18.9700]]]}]
    dp.export_dxf(ring, props, str(out), neighbors=neighbours, roads=roads)

    doc = ezdxf.readfile(str(out))
    msp = doc.modelspace()
    used = {e.dxf.layer for e in msp}
    for layer in ("C-PLOT-BDY", "C-ROAD-ALIGN", "C-ADJN-PLOTS", "C-SETBACK-3M",
                  "C-RESTRICT-ZONE", "C-NORTH-ARROW", "C-TITLE-BLOCK", "C-ANNO-DIMS"):
        assert layer in used, f"{layer} is declared but empty"

    text = " ".join(
        (e.plain_text() if hasattr(e, "plain_text") else e.dxf.text)
        for e in msp if e.dxftype() in ("TEXT", "MTEXT")
    )
    for token in ("LAYER LEGEND", "PLOT DATA", "GROSS PLOT AREA", "ABUTTING ROAD",
                  "CRZ STATUS", "1 CAD unit = 1 metre"):
        assert token in text, f"legend is missing {token!r}"


def test_dxf_geometry_stays_within_sane_extents(tmp_path):
    """Regression: neighbour rings arrived in Web Mercator and drew at ~8e11."""
    ezdxf = pytest.importorskip("ezdxf")
    out = tmp_path / "x.dxf"
    neighbours = [{"cts_no": "1", "rings": [[[72.8216, 18.9700], [72.8225, 18.9700],
                                             [72.8225, 18.9712], [72.8216, 18.9700]]]}]
    dp.export_dxf(RING, PROPS, str(out), neighbors=neighbours)
    doc = ezdxf.readfile(str(out))
    coords = [c for e in doc.modelspace() if e.dxftype() == "LWPOLYLINE"
              for p in e.get_points("xy") for c in (p[0], p[1])]
    assert coords and max(abs(c) for c in coords) < 5000


def test_exports_do_not_crash_on_none_area(tmp_path):
    """MALABAR HILL 16/738 really does return a null area from MCGM."""
    props = dict(PROPS, area_sqm=None)
    dp.export_geojson(RING, props, str(tmp_path / "a.geojson"))
    dp.export_kml(RING, props, str(tmp_path / "a.kml"))
    dp.export_dxf(RING, props, str(tmp_path / "a.dxf"), neighbors=[])


# --------------------------------------------------------------------------
# CLI argument handling
# --------------------------------------------------------------------------

def test_cli_usage_exits_nonzero_without_args(capsys):
    assert dp.main([]) == 1
    assert "Usage:" in capsys.readouterr().out


def test_cli_rejects_bad_village_without_network(capsys):
    code = dp.main(["1' OR '1'='1", "947"])
    assert code == 1
    assert "unsupported characters" in capsys.readouterr().out
