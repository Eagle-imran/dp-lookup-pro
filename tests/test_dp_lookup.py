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
    closed = [*SQUARE, SQUARE[0]]
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

def test_lookup_accepts_an_on_data_callback():
    import inspect
    sig = inspect.signature(dp.lookup_plot_pro)
    assert "on_data" in sig.parameters
    assert sig.parameters["on_data"].default is None


def test_summary_marks_a_pending_snapshot_as_still_building():
    """The early snapshot must not read as a finished report."""
    snap = {
        "plot_identity": {"village": "WORLI", "cts_no": "733", "ward": "G/S",
                          "area_sqm": 1317.74, "area_source": "approved (MCGM)"},
        "planning_remarks": {"status_badge": "CLEAR", "zone": "R",
                             "reservation": {"code": "None", "type": "None"},
                             "designation": {"description": "None"},
                             "dp_modification": {"approval_no": "None"}},
        "regulatory_and_infrastructure": {"crz_status": "YES (CRZ II)", "metro_buffer": "NO",
                                          "abutting_road": {"name": "B G KHER", "width": "18.30 M"}},
        "spatial_cluster": {"adjoining_plots_count": 3, "adjoining_cts_plots": []},
        "export_files": {"bundle_folder": "./o", "pdf_report": "./o/r.pdf",
                         "master_excel_register": "./o/x.xlsx"},
        "metadata": {"execution_time_ms": 650, "cached_result": False, "complete": True,
                     "documents_pending": True, "warnings": [], "notes": []},
    }
    text = dp.format_result_human(snap)
    # the planning answer is fully present in the early snapshot
    for token in ("WORLI", "CTS 733", "YES (CRZ II)", "1,317.74"):
        assert token in text


def test_village_list_is_complete_and_sorted():
    assert len(dp.MCGM_VILLAGES) == 128
    assert list(dp.MCGM_VILLAGES) == sorted(dp.MCGM_VILLAGES)
    for known in ("BANDRA-A", "WORLI", "MALABAR HILL", "KURLA - 1", "BHANDUP-E", "MOHILI"):
        assert known in dp.MCGM_VILLAGES


@pytest.mark.parametrize("typo,expected", [
    ("BANDRA", "BANDRA-A"),      # the commonest mistake of all
    ("KURLA", "KURLA - 1"),
    ("BHANDUP", "BHANDUP-E"),
    ("MALABAR", "MALABAR HILL"),
    ("worli", "WORLI"),
])
def test_suggestions_catch_the_common_locality_mistakes(typo, expected):
    assert expected in dp.suggest_villages(typo)


def test_suggestions_are_empty_for_nonsense():
    assert dp.suggest_villages("") == []
    assert dp.suggest_villages("ZZZZQQQQ") == []


def test_list_villages_flag(capsys):
    assert dp.main(["--list-villages"]) == 0
    out = capsys.readouterr().out
    assert "128 valid MCGM village names" in out
    assert "BANDRA-A" in out
    assert "NOT valid" in out


def test_human_summary_reads_cleanly():
    result = {
        "plot_identity": {"village": "WORLI", "cts_no": "733", "ward": "G/S",
                          "area_sqm": 1317.74, "area_source": "approved (MCGM AREA_APP_SQ_MTRS)"},
        "planning_remarks": {"status_badge": "CLEAR", "zone": "R",
                             "reservation": {"code": "None", "type": "None"},
                             "designation": {"description": "None"},
                             "dp_modification": {"approval_no": "None"}},
        "regulatory_and_infrastructure": {"crz_status": "YES (CRZ II)", "metro_buffer": "NO",
                                          "abutting_road": {"name": "B G KHER", "width": "18.30 M"}},
        "spatial_cluster": {"adjoining_plots_count": 3, "adjoining_cts_plots": [{"cts_no": "734"}]},
        "export_files": {"bundle_folder": "./output/x", "pdf_report": "./output/x/r.pdf",
                         "master_excel_register": "./output/dp-lookups.xlsx"},
        "metadata": {"execution_time_ms": 7100, "cached_result": False, "complete": True,
                     "warnings": [], "notes": []},
    }
    text = dp.format_result_human(result)
    for token in ("WORLI", "CTS 733", "1,317.74", "YES (CRZ II)", "B G KHER", "7.1s"):
        assert token in text
    assert "{" not in text, "summary should not leak raw JSON"


def test_human_summary_flags_a_derived_area_and_incompleteness():
    result = {
        "plot_identity": {"village": "TARDEO", "cts_no": "264", "ward": "D",
                          "area_sqm": 2539.25, "area_source": "derived from plot geometry"},
        "planning_remarks": {"status_badge": "CLEAR", "zone": "R",
                             "reservation": {"code": "None", "type": "None"},
                             "designation": {"description": "None"},
                             "dp_modification": {"approval_no": "None"}},
        "regulatory_and_infrastructure": {"crz_status": "NO", "metro_buffer": "NO",
                                          "abutting_road": {"name": "None", "width": "None"}},
        "spatial_cluster": {"adjoining_plots_count": 0, "adjoining_cts_plots": []},
        "export_files": {"bundle_folder": "./o", "pdf_report": "./o/r.pdf",
                         "master_excel_register": "./o/x.xlsx"},
        "metadata": {"execution_time_ms": 900, "cached_result": False, "complete": False,
                     "warnings": ["3 of 9 road probes failed"], "notes": ["area derived"]},
    }
    text = dp.format_result_human(result)
    assert "derived from boundary" in text
    assert "INCOMPLETE" in text
    assert "road probes failed" in text


def test_human_summary_renders_an_error_without_traceback():
    text = dp.format_result_human({"error": "'BANDRA' is not a valid MCGM village name."})
    assert "BANDRA" in text and "Could not complete" in text


def test_cli_usage_exits_nonzero_without_args(capsys):
    assert dp.main([]) == 1
    assert "Usage:" in capsys.readouterr().out


def test_cli_rejects_bad_village_without_network(capsys):
    code = dp.main(["1' OR '1'='1", "947"])
    assert code == 1
    assert "unsupported characters" in capsys.readouterr().out


# --------------------------------------------------------------------------
# Extracted pure helpers — previously buried inside a 730-line function and
# therefore only reachable through a live network call.
# --------------------------------------------------------------------------

def test_mercator_roundtrips_against_the_known_plot_centroid():
    """WORLI 733's centroid, verified live: 19.011989 N, 72.817102 E."""
    lon, lat = dp.mercator_to_wgs84(8106574.0, 2151800.0, precision=4)
    assert 72.0 < lon < 73.5
    assert 18.5 < lat < 19.5


def test_mercator_is_monotonic():
    assert dp.mercator_to_wgs84(1e6, 0)[0] > dp.mercator_to_wgs84(0, 0)[0]
    assert dp.mercator_to_wgs84(0, 1e6)[1] > dp.mercator_to_wgs84(0, 0)[1]


# ---- area resolution ----

def test_area_prefers_the_mcgm_approved_figure():
    got = dp.resolve_plot_area({"AREA_APP_SQ_MTRS": 1317.74, "SHAPE.AREA": 1321.74})
    assert got["area_sqm"] == 1317.74
    assert "approved" in got["area_source"]
    assert got["note"] is None


def test_area_falls_back_to_geometry_and_says_so():
    """MALABAR HILL 518 and TARDEO 264 really do have no approved area."""
    got = dp.resolve_plot_area({"AREA_APP_SQ_MTRS": None, "SHAPE.AREA": 2450.15659})
    assert got["area_sqm"] == 2450.16
    assert "derived" in got["area_source"]
    assert "indicative only" in got["note"]


@pytest.mark.parametrize("attrs", [
    {"AREA_APP_SQ_MTRS": None, "SHAPE.AREA": None},
    {"AREA_APP_SQ_MTRS": 0, "SHAPE.AREA": 0},
    {},
])
def test_area_reports_unavailable_rather_than_guessing(attrs):
    got = dp.resolve_plot_area(attrs)
    assert got["area_sqm"] is None
    assert got["area_source"] == "unavailable"


# ---- geometry ----

MERC_RING = [[[8106500.0, 2151700.0], [8106600.0, 2151700.0],
              [8106600.0, 2151800.0], [8106500.0, 2151800.0]]]


def test_prepare_geometry_returns_a_usable_window():
    g = dp.prepare_geometry(MERC_RING)
    assert g["mcx"] == pytest.approx(8106550.0)
    assert g["mcy"] == pytest.approx(2151750.0)
    assert g["d"] >= 50                      # floor, so tiny plots still get a map window
    assert 72 < g["lon"] < 73 and 18 < g["lat"] < 20
    assert len(g["wgs_rings"][0]) == 4


def test_prepare_geometry_floors_the_window_for_a_tiny_plot():
    tiny = [[[8106500.0, 2151700.0], [8106504.0, 2151700.0],
             [8106504.0, 2151704.0], [8106500.0, 2151704.0]]]
    assert dp.prepare_geometry(tiny)["d"] == 50


# ---- bundle folder ----

@pytest.mark.parametrize("village,cts,expected", [
    ("WORLI", "733", "worli_cts_733"),
    ("MALABAR HILL", "16/738", "malabar_hill_cts_16-738"),
    ("BANDRA-A", "409", "bandra-a_cts_409"),
    ("  TARDEO  ", "264", "tardeo_cts_264"),
])
def test_bundle_folder_is_filesystem_safe(village, cts, expected):
    name = dp.bundle_folder_name(village, cts)
    assert name == expected
    assert "/" not in name and "\\" not in name and " " not in name


# ---- road selection ----

def test_road_prefers_a_named_road_with_a_width():
    chosen = dp.select_road({
        "a": {"name": "Exisiting Road", "width": "N/A"},
        "b": {"name": "B G KHER", "width": "18.30 M"},
    })
    assert chosen == {"name": "B G KHER", "width": "18.30 M"}


def test_road_accepts_a_width_without_a_name():
    """MOHILI 732 returns an unnamed road carrying a real 21.35 m width."""
    chosen = dp.select_road({"a": {"name": "Road", "width": "21.35"}})
    assert chosen["width"] == "21.35"


def test_road_falls_back_to_the_generic_record():
    """WORLI 886: MCGM's own typo, no width. Better than reporting nothing."""
    chosen = dp.select_road({"a": {"name": "Exisiting Road", "width": "N/A"}})
    assert chosen == {"name": "Exisiting Road", "width": "N/A"}


def test_road_reports_none_when_nothing_was_found():
    assert dp.select_road({}) == {"name": "None", "width": "None"}


# ---- CRZ tier ----

@pytest.mark.parametrize("item,expected", [
    (None, "NO (Outside CRZ Buffer)"),
    ({"attributes": {"category": "II"}}, "YES (CRZ II)"),          # layer 14
    ({"attributes": {"Category": "II"}}, "YES (CRZ II)"),          # layer 1548
    ({"attributes": {"CLASS": "CRZ II"}}, "YES (CRZ II)"),         # layer 1264, pre-prefixed
    ({"attributes": {"category": "III"}}, "YES (CRZ III)"),
])
def test_crz_tier_is_read_from_whichever_attribute_the_layer_uses(item, expected):
    assert dp.crz_flag_from(item) == expected


def test_crz_falls_back_to_the_layer_name_when_no_tier_is_present():
    got = dp.crz_flag_from({"layerName": "CRZ", "attributes": {"category": "Null"}})
    assert got == "YES (CRZ)"


# ---- status precedence ----

def test_a_dp_modification_outranks_everything():
    got = dp.derive_status({"x": 1}, {"y": 1}, {"z": 1}, "Hospital", "EH1.2",
                           "RC1", "Garden", "MCP/7526")
    assert "MODIFIED" in got["badge"]
    assert "MCP/7526" in got["summary"]


def test_a_designation_outranks_a_reservation():
    got = dp.derive_status(None, {"y": 1}, {"z": 1}, "Fire Station", "EPU1.1",
                           "RC1", "Garden", "None")
    assert "RESERVED / DESIGNATED" in got["badge"]
    assert "Fire Station" in got["summary"]


def test_a_reservation_is_reported_when_there_is_no_designation():
    got = dp.derive_status(None, None, {"z": 1}, "None", "None", "RC1", "Garden", "None")
    assert "RESERVED" in got["badge"] and "Garden" in got["badge"]


def test_a_plot_with_nothing_against_it_is_clear():
    got = dp.derive_status(None, None, None, "None", "None", "None", "None", "None")
    assert "CLEAR" in got["badge"]
    assert got["summary"] == "Unreserved Land Parcel"
