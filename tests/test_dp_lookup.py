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


# --------------------------------------------------------------------------
# ArcGIS request payloads. These mirror requests validated against the live
# server; the tests exist so a future tidy-up cannot silently change them.
# --------------------------------------------------------------------------

def test_planning_layer_string_is_exact():
    assert dp.planning_layers([14, 1264, 1548]) == "visible:0,46,47,192,1550,14,1264,1548"


def test_road_layers_include_the_polygon_road_layers():
    """193/194 return `paths`, 44/45 return `rings`. Both are needed."""
    for layer in ("193", "194", "44", "45"):
        assert layer in dp.ROAD_LAYERS


def test_identify_payload_shape():
    got = dp.identify_payload(100.0, 200.0, "visible:13", 10.0, 20.0, 50.0,
                              tolerance=30, return_geometry=True)
    assert got["geometry"] == "100.0,200.0"
    assert got["geometryType"] == "esriGeometryPoint"
    assert got["sr"] == "102100"
    assert got["tolerance"] == "30"
    assert got["returnGeometry"] == "true"
    assert got["imageDisplay"] == "1000,1000,96"
    assert got["mapExtent"] == "-40.0,-30.0,60.0,70.0"
    assert got["f"] == "json"


def test_identify_payload_returns_geometry_as_a_string_not_a_bool():
    """ArcGIS wants the literal strings; a Python bool would be sent as True."""
    assert dp.identify_payload(0, 0, "x", 0, 0, 1, 30, False)["returnGeometry"] == "false"


def test_map_export_params_shape():
    got = dp.map_export_params(1.0, 2.0, 3.0, 4.0)
    assert got["bbox"] == "1.0,2.0,3.0,4.0"
    assert got["size"] == "1000,1000"
    assert got["f"] == "image"
    assert got["dpi"] == "144"


# ---- probe geometry ----

SQ_RING = [[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0]]


def test_road_probes_keep_the_centroid_and_both_corners():
    """Dropping these regressed WORLI 947's named road; they are deliberate."""
    pts = dp.road_probe_points(SQ_RING, 50.0, 50.0, [0.0, 100.0], [0.0, 100.0])
    assert pts[0] == (50.0, 50.0)
    assert pts[1] == (0.0, 0.0)
    assert pts[2] == (100.0, 100.0)


def test_road_probes_are_capped_and_pushed_outside_the_plot():
    pts = dp.road_probe_points(SQ_RING, 50.0, 50.0, [0.0, 100.0], [0.0, 100.0])
    assert len(pts) == 3 + dp.ROAD_EDGE_PROBE_LIMIT
    # every edge probe must sit outside the square, never inside it
    for x, y in pts[3:]:
        assert not (0.0 < x < 100.0 and 0.0 < y < 100.0), f"probe ({x},{y}) is inside the plot"


def test_road_probes_use_three_distances_per_edge():
    assert len(dp.ROAD_EDGE_NUDGES) == 3
    pts = dp.road_probe_points(SQ_RING, 50.0, 50.0, [0.0, 100.0], [0.0, 100.0])
    # the four edges of a square are equal length, so all three nudges appear
    dists = {round(max(abs(x - 50.0), abs(y - 50.0)), 1) for x, y in pts[3:]}
    assert len(dists) >= 3


def test_road_probes_survive_a_degenerate_ring():
    """A zero-length segment must not divide by zero."""
    ring = [[0.0, 0.0], [0.0, 0.0], [10.0, 0.0], [10.0, 10.0]]
    assert dp.road_probe_points(ring, 5.0, 5.0, [0.0, 10.0], [0.0, 10.0])


def test_neighbour_probes_are_four_cardinal_offsets():
    pts = dp.neighbour_probe_points(0.0, 0.0, 100.0)
    assert len(pts) == 4
    assert set(pts) == {(70.0, 0.0), (-70.0, 0.0), (0.0, 70.0), (0.0, -70.0)}


def test_neighbour_probe_offset_has_a_floor():
    """A tiny plot still needs to reach far enough to find a neighbour."""
    assert dp.neighbour_probe_points(0.0, 0.0, 1.0) == [
        (15.0, 0.0), (-15.0, 0.0), (0.0, 15.0), (0.0, -15.0)]


# --------------------------------------------------------------------------
# Image renderers — previously inline in lookup_plot_pro and only reachable
# through a live fetch of the MCGM map and nine Esri tiles.
# --------------------------------------------------------------------------

def _png_bytes(size=(256, 256), colour=(10, 120, 30)):
    import io as _io

    from PIL import Image
    buf = _io.BytesIO()
    Image.new("RGB", size, colour).save(buf, format="PNG")
    return buf.getvalue()


DP_LABELS = {"cts": "733", "village": "WORLI", "ward": "G/S", "zone": "R",
             "area": 1317.74, "status": "CLEAR (No Reservation)"}
SAT_LABELS = {"cts": "733", "village": "WORLI", "ward": "G/S",
              "lat": 19.011989, "lon": 72.817102, "neighbours": 3}
MERC_SQUARE = [[[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0]]]


def test_dp_map_renders_over_the_server_image():
    img = dp.render_dp_map(_png_bytes((1000, 1000)), MERC_SQUARE,
                           bbox=(0, 0, 100, 100), size=(1000, 1000), labels=DP_LABELS)
    assert img.size == (1000, 1000)
    assert img.mode == "RGBA"


def test_dp_map_still_renders_when_the_server_image_is_missing():
    """A failed /export must not abort the report."""
    img = dp.render_dp_map(None, MERC_SQUARE, bbox=(0, 0, 100, 100),
                           size=(400, 400), labels=DP_LABELS)
    assert img.size == (400, 400)


def test_dp_map_draws_the_plot_boundary_in_red():
    img = dp.render_dp_map(None, MERC_SQUARE, bbox=(0, 0, 100, 100),
                           size=(600, 600), labels=DP_LABELS).convert("RGB")
    px = img.load()
    reds = sum(1 for x in range(0, 600, 3) for y in range(0, 600, 3)
               if px[x, y][0] > 180 and px[x, y][1] < 110 and px[x, y][2] < 130)
    assert reds > 50, "no red boundary drawn"


def test_satellite_stitches_a_grid():
    tiles = [_png_bytes() for _ in range(9)]
    coords = [(x, y) for y in range(3) for x in range(3)]
    img = dp.stitch_satellite(tiles, coords, 3, [[[72.8, 19.0], [72.81, 19.0], [72.81, 19.01]]],
                              bounds=(19.02, 72.79, 18.99, 72.82), labels=SAT_LABELS)
    assert img.size == (768, 768)


def test_satellite_survives_missing_and_failed_tiles():
    """Tiles arrive as bytes, None, or exceptions when a fetch failed."""
    tiles = [_png_bytes(), None, RuntimeError("timeout"), b"", _png_bytes(),
             None, None, _png_bytes(), None]
    coords = [(x, y) for y in range(3) for x in range(3)]
    img = dp.stitch_satellite(tiles, coords, 3, [[[72.8, 19.0], [72.81, 19.0], [72.81, 19.01]]],
                              bounds=(19.02, 72.79, 18.99, 72.82), labels=SAT_LABELS)
    assert img.size == (768, 768)


def test_satellite_survives_corrupt_tile_bytes():
    tiles = [b"not a png"] * 9
    coords = [(x, y) for y in range(3) for x in range(3)]
    img = dp.stitch_satellite(tiles, coords, 3, [], bounds=(19.02, 72.79, 18.99, 72.82),
                              labels=SAT_LABELS)
    assert img.size == (768, 768)


def test_renderers_accept_a_multi_ring_plot():
    two = [*MERC_SQUARE, [[10.0, 10.0], [20.0, 10.0], [20.0, 20.0], [10.0, 20.0]]]
    assert dp.render_dp_map(None, two, (0, 0, 100, 100), (300, 300), DP_LABELS)


# --------------------------------------------------------------------------
# Text metrics, and the sheet faults that only AutoCAD revealed
#
# WORLI 733 and AMBIVALI 807 both passed every geometry check while carrying 16
# faults each: legend rows outside their panel, the UTM tie-in lying across a
# dimension, two grid labels stacked at the sheet corner. Whether text collides
# depends on the rendered width of a glyph, so none of it was reachable without
# measuring the text.
# --------------------------------------------------------------------------

def _dxf_texts(msp):
    """(entity, measured box) for every TEXT that can be measured."""
    return [(e, dp.text_extents(e)) for e in msp.query("TEXT")
            if dp.text_extents(e) is not None]


def _title_block_rects(msp):
    rects = []
    for e in msp.query("LWPOLYLINE[layer=='C-TITLE-BLOCK']"):
        pts = e.get_points("xy")
        if len(pts) == 4:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            rects.append((min(xs), min(ys), max(xs), max(ys)))
    rects.sort(key=lambda r: (r[2] - r[0]) * (r[3] - r[1]), reverse=True)
    return rects


def test_text_extents_measures_width_and_respects_rotation():
    ezdxf = pytest.importorskip("ezdxf")
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    flat = msp.add_text("MMMMMMMMMM", dxfattribs={"height": 2.0})
    flat.set_placement((0.0, 0.0))
    box = dp.text_extents(flat)
    assert box is not None
    assert box[2] - box[0] > 4.0, "ten characters cannot be narrower than two heights"
    assert box[3] - box[1] == pytest.approx(2.0, abs=0.6)

    turned = msp.add_text("MMMMMMMMMM", dxfattribs={"height": 2.0, "rotation": 90.0})
    turned.set_placement((0.0, 0.0))
    tbox = dp.text_extents(turned)
    # Rotated ninety degrees, the long axis has to become the vertical one.
    assert tbox[3] - tbox[1] > tbox[2] - tbox[0]


def test_boxes_overlap_and_unmeasurable_text_never_collides():
    assert dp.boxes_overlap((0, 0, 2, 2), (1, 1, 3, 3))
    assert not dp.boxes_overlap((0, 0, 2, 2), (2.5, 0, 4, 2))
    assert not dp.boxes_overlap(None, (0, 0, 1, 1))
    assert not dp.boxes_overlap((0, 0, 1, 1), None)


def test_nudge_text_clear_moves_a_label_out_of_the_way():
    ezdxf = pytest.importorskip("ezdxf")
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    label = msp.add_text("CTS 733A", dxfattribs={"height": 1.0})
    label.set_placement((0.0, 0.0))
    obstacle = dp.text_extents(label)
    start_y = float(label.dxf.insert[1])

    assert dp.nudge_text_clear(label, [obstacle], step=1.5, limit=10)
    assert float(label.dxf.insert[1]) > start_y
    assert not dp.boxes_overlap(dp.text_extents(label), obstacle)


def test_nudge_text_clear_reports_failure_rather_than_looping():
    ezdxf = pytest.importorskip("ezdxf")
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    label = msp.add_text("X", dxfattribs={"height": 1.0})
    label.set_placement((0.0, 0.0))
    # An obstacle taller than the nudge budget can never be escaped.
    assert not dp.nudge_text_clear(label, [(-50, -50, 50, 50)], step=0.1, limit=3)


def test_legend_height_accounts_for_the_plot_data_rows():
    """Regression: the height was `lg_row * (n_legend + 9.5)`, which counted none
    of the PLOT DATA rows, so the panel border cut across the last three."""
    lg_row = 3.5
    tall = dp.legend_column_height(lg_row, 12, 10)
    assert tall > lg_row * (12 + 9.5), "must exceed the old under-count"
    # Adding a data row must make the panel taller by exactly that row.
    assert dp.legend_column_height(lg_row, 12, 11) - tall == pytest.approx(lg_row)


def test_long_road_name_wraps_instead_of_escaping_the_panel():
    """AMBIVALI 807's frontage overran the panel by 19.8 m as a single row."""
    rows = dp.legend_data_row(
        "ABUTTING ROAD",
        "Jay Prakash Road Part II Dadabhai Road to Versova Metro. (27.4 M.)")
    assert len(rows) > 1, "a 65-character value has to wrap"
    assert all(len(r) <= 16 + 2 + dp.LEGEND_VALUE_MAX_CHARS for r in rows)
    assert rows[0].startswith("ABUTTING ROAD   : ")
    # Continuation lines are indented under the value, not under the label.
    assert rows[1].startswith(" " * 16)
    assert "Versova" in " ".join(rows), "wrapping must not drop words"


def test_plot_data_prints_both_areas_and_names_the_gap():
    """AMBIVALI 807: MCGM's record says 2019.00 but its own polygon measures
    2142.25. Printing one figure invites an FSI calculation off an unreconciled
    number."""
    props = dict(PROPS, area_sqm=2019.0, area_source="approved (MCGM AREA_APP_SQ_MTRS)")
    rows = dp.legend_data_rows(props, {3.0: True, 6.0: True}, measured_area_sqm=2142.25)
    joined = " ".join(rows)
    assert "2019.0" in joined
    assert "2142.25" in joined
    assert "+6.10%" in joined, f"the gap must be stated, got: {joined}"


def test_plot_data_omits_the_delta_when_the_area_is_derived():
    """A derived area IS the boundary measurement; a delta against itself is noise."""
    props = dict(PROPS, area_source="derived from boundary")
    rows = dp.legend_data_rows(props, {3.0: True}, measured_area_sqm=462.28)
    assert "% vs record" not in " ".join(rows)


def test_dxf_keeps_every_label_inside_the_sheet_border(tmp_path):
    ezdxf = pytest.importorskip("ezdxf")
    out = tmp_path / "x.dxf"
    props = dict(PROPS, crz_buffer_flag="YES (CRZ II)", metro_buffer_flag="YES",
                 abutting_road="Jay Prakash Road Part II Dadabhai Road to Versova Metro.",
                 road_width="27.4 M.")
    roads = [[[72.8195, 18.9698], [72.8220, 18.9698]]]
    neighbours = [{"cts_no": "948", "rings": [[[72.8210, 18.9700], [72.8219, 18.9700],
                                               [72.8219, 18.9709], [72.8210, 18.9700]]]}]
    dp.export_dxf(RING, props, str(out), neighbors=neighbours, roads=roads)

    msp = ezdxf.readfile(str(out)).modelspace()
    rects = _title_block_rects(msp)
    assert rects, "the sheet border is missing"
    sheet = rects[0]
    for entity, box in _dxf_texts(msp):
        assert box[0] >= sheet[0] - 0.01 and box[2] <= sheet[2] + 0.01, \
            f"{entity.dxf.text!r} escapes the border horizontally"
        assert box[1] >= sheet[1] - 0.01 and box[3] <= sheet[3] + 0.01, \
            f"{entity.dxf.text!r} escapes the border vertically"


def test_dxf_legend_rows_stay_inside_their_panel(tmp_path):
    """Regression: four rows overran the panel edge and three fell below it."""
    ezdxf = pytest.importorskip("ezdxf")
    out = tmp_path / "x.dxf"
    props = dict(PROPS, abutting_road="KHAN ABDUL GAFFAR KHAN MARG", road_width="N/A")
    dp.export_dxf(RING, props, str(out), neighbors=[])

    msp = ezdxf.readfile(str(out)).modelspace()
    rects = _title_block_rects(msp)
    panels = rects[1:]
    assert panels, "the legend panel is missing"
    for entity, box in _dxf_texts(msp):
        for panel in panels:
            if panel[0] - 0.01 <= box[0] <= panel[2] + 0.01 and box[1] <= panel[3]:
                assert box[2] <= panel[2] + 0.01, \
                    f"{entity.dxf.text!r} overruns the panel by {box[2] - panel[2]:.2f}"
                assert box[1] >= panel[1] - 0.01, \
                    f"{entity.dxf.text!r} falls {panel[1] - box[1]:.2f} below the panel"
                break


def test_dxf_drawing_labels_do_not_collide(tmp_path):
    """The three WORLI 733 / AMBIVALI 807 collisions, in one drawing: stacked grid
    corner labels, a neighbour label on a dimension, and two dimensions on each
    other."""
    ezdxf = pytest.importorskip("ezdxf")
    out = tmp_path / "x.dxf"
    # A ring with two deliberately short adjacent edges, which is what put
    # AMBIVALI 807's '6.20m' and '3.47m' on top of one another.
    ring = [[[72.8200, 18.9700], [72.8210, 18.9700], [72.8210, 18.9706],
             [72.82093, 18.97064], [72.82086, 18.97067], [72.8200, 18.9710],
             [72.8200, 18.9700]]]
    props = dict(PROPS, crz_buffer_flag="YES (CRZ II)", metro_buffer_flag="YES")
    neighbours = [{"cts_no": "733A", "rings": [[[72.8210, 18.9701], [72.8214, 18.9701],
                                                [72.8214, 18.9705], [72.8210, 18.9701]]]}]
    dp.export_dxf(ring, props, str(out), neighbors=neighbours)

    msp = ezdxf.readfile(str(out)).modelspace()
    panels = _title_block_rects(msp)[1:]

    def in_panel(box):
        return any(p[0] - 0.01 <= box[0] <= p[2] + 0.01 for p in panels)

    drawing = [(e, b) for e, b in _dxf_texts(msp) if not in_panel(b)]
    for i, (e1, b1) in enumerate(drawing):
        for e2, b2 in drawing[i + 1:]:
            assert not dp.boxes_overlap(b1, b2), \
                f"{e1.dxf.text!r} [{e1.dxf.layer}] overlaps {e2.dxf.text!r} [{e2.dxf.layer}]"


def test_dxf_grid_does_not_label_the_corner_twice(tmp_path):
    """The X label row and the Y label column both emitted a label at the
    bottom-left corner, at identical coordinates."""
    ezdxf = pytest.importorskip("ezdxf")
    out = tmp_path / "x.dxf"
    dp.export_dxf(RING, PROPS, str(out), neighbors=[])
    msp = ezdxf.readfile(str(out)).modelspace()
    points = [(round(e.dxf.insert[0], 4), round(e.dxf.insert[1], 4))
              for e in msp.query("TEXT[layer=='0_GRID_AXIS']")]
    assert len(points) == len(set(points)), "two grid labels share an insertion point"


def test_dxf_layers_carry_lineweights_so_the_sheet_plots_with_hierarchy(tmp_path):
    """Every layer defaulted to -3, so a plotted sheet rendered the metric grid at
    the same weight as the plot boundary."""
    ezdxf = pytest.importorskip("ezdxf")
    out = tmp_path / "x.dxf"
    dp.export_dxf(RING, PROPS, str(out), neighbors=[])
    doc = ezdxf.readfile(str(out))
    weights = {lay.dxf.name: lay.dxf.lineweight for lay in doc.layers
               if lay.dxf.name not in ("0", "Defpoints")}
    assert weights and all(w > 0 for w in weights.values()), \
        f"layers still on the default weight: {[k for k, v in weights.items() if v <= 0]}"
    assert weights["C-PLOT-BDY"] > weights["0_GRID_AXIS"], \
        "the plot boundary must plot heavier than the reference grid"


def test_dxf_plot_fill_is_transparent_so_an_underlay_shows_through(tmp_path):
    """An opaque solid fill hid survey underlays and satellite images - most of
    what an architect puts under this drawing."""
    ezdxf = pytest.importorskip("ezdxf")
    out = tmp_path / "x.dxf"
    dp.export_dxf(RING, PROPS, str(out), neighbors=[])
    hatches = list(ezdxf.readfile(str(out)).modelspace().query("HATCH"))
    assert hatches, "the plot fill is missing"
    for hatch in hatches:
        assert hatch.transparency > 0.0


def test_dxf_annotation_is_readable_on_a_very_small_plot(tmp_path):
    """BANDRA-A 409 is 7.6 x 16.4 m. The UTM tie-in string used to render roughly
    six times the plot width across it."""
    ezdxf = pytest.importorskip("ezdxf")
    out = tmp_path / "x.dxf"
    # ~8 x 16 m
    ring = [[[72.8200, 18.9700], [72.820076, 18.9700],
             [72.820076, 18.970144], [72.8200, 18.970144], [72.8200, 18.9700]]]
    dp.export_dxf(ring, dict(PROPS, area_sqm=125.0), str(out), neighbors=[])

    msp = ezdxf.readfile(str(out)).modelspace()
    panels = _title_block_rects(msp)[1:]
    bdy = next(iter(msp.query("LWPOLYLINE[layer=='C-PLOT-BDY']")))
    xs = [p[0] for p in bdy.get_points("xy")]
    plot_w = max(xs) - min(xs)

    for entity, box in _dxf_texts(msp):
        if any(p[0] - 0.01 <= box[0] <= p[2] + 0.01 for p in panels):
            continue
        assert (box[2] - box[0]) < plot_w * 2.5, (
            f"{entity.dxf.text!r} is {(box[2] - box[0]) / plot_w:.1f}x the plot width")


def test_metro_buffer_restriction_is_actually_drawn(tmp_path):
    """Regression: the lookup sets this flag to 'YES (Metro Buffer Zone)' but the
    DXF tested `== "YES"`, so the metro restriction was silently missing from every
    drawing. AMBIVALI 807 is in a metro buffer and its DXF said nothing."""
    ezdxf = pytest.importorskip("ezdxf")
    out = tmp_path / "x.dxf"
    props = dict(PROPS, crz_buffer_flag="NO (Outside CRZ Buffer)",
                 metro_buffer_flag="YES (Metro Buffer Zone)")
    dp.export_dxf(RING, props, str(out), neighbors=[])

    msp = ezdxf.readfile(str(out)).modelspace()
    circles = list(msp.query("CIRCLE[layer=='C-RESTRICT-ZONE']"))
    assert circles, "no metro influence circle drawn"
    notes = [e.dxf.text for e in msp.query("TEXT[layer=='C-RESTRICT-ZONE']")]
    assert any("METRO" in n for n in notes), f"no metro note drawn, got {notes}"


def test_restriction_layer_carries_geometry_not_just_a_legend_swatch(tmp_path):
    """`C-RESTRICT-ZONE` counted as non-empty purely because the legend draws a
    sample line on it, which hid the metro bug from the empty-layer test."""
    ezdxf = pytest.importorskip("ezdxf")
    out = tmp_path / "x.dxf"
    props = dict(PROPS, crz_buffer_flag="YES (CRZ II)",
                 metro_buffer_flag="YES (Metro Buffer Zone)")
    dp.export_dxf(RING, props, str(out), neighbors=[])

    msp = ezdxf.readfile(str(out)).modelspace()
    # The legend swatch is a single short LINE inside the panel. Real content is
    # the notes and the influence circle.
    real = [e for e in msp if e.dxf.layer == "C-RESTRICT-ZONE"
            and e.dxftype() in ("TEXT", "CIRCLE")]
    assert len(real) >= 2, "restriction layer carries only its legend swatch"


# --------------------------------------------------------------------------
# Road clipping
# --------------------------------------------------------------------------

def test_clip_keeps_a_segment_that_crosses_with_no_vertex_inside():
    """MCGM road centrelines can have vertices a kilometre apart. Testing
    vertices alone dropped roads running straight past the plot."""
    runs = dp.clip_path_to_window([(-1000.0, 5.0), (1000.0, 5.0)], -50, -50, 50, 50)
    assert len(runs) == 1
    (x0, _), (x1, _) = runs[0][0], runs[0][-1]
    # Clipped to the window, not kept at full length, or the sheet border follows it out.
    assert x0 == pytest.approx(-50.0) and x1 == pytest.approx(50.0)


def test_clip_drops_a_path_that_misses_the_window():
    assert dp.clip_path_to_window([(-1000.0, 500.0), (1000.0, 500.0)], -50, -50, 50, 50) == []


def test_clip_splits_a_path_that_leaves_and_reenters():
    path = [(-100.0, 0.0), (0.0, 0.0), (0.0, 500.0), (10.0, 500.0), (10.0, 0.0), (100.0, 0.0)]
    runs = dp.clip_path_to_window(path, -50, -50, 50, 50)
    assert len(runs) == 2, f"expected two runs, got {len(runs)}"


def test_clip_keeps_a_wholly_contained_path_intact():
    path = [(-10.0, -10.0), (0.0, 0.0), (10.0, 10.0)]
    runs = dp.clip_path_to_window(path, -50, -50, 50, 50)
    assert len(runs) == 1
    assert len(runs[0]) == 3


def test_sparse_road_is_drawn_on_the_dxf(tmp_path):
    """Regression: the same road was drawn when densely vertexed and dropped
    entirely when sparsely vertexed. AMBIVALI 807 had a named 27.4 m frontage and
    an empty C-ROAD-ALIGN layer."""
    ezdxf = pytest.importorskip("ezdxf")
    props = dict(PROPS, abutting_road="Jay Prakash Road", road_width="27.4 M.")
    # Runs due east past the plot's south edge; vertices ~1.1 km either side, so
    # neither lands anywhere near the plot.
    sparse = [[[72.800, 18.96995], [72.850, 18.96995]]]
    out = tmp_path / "x.dxf"
    dp.export_dxf(RING, props, str(out), neighbors=[], roads=sparse)

    msp = ezdxf.readfile(str(out)).modelspace()
    assert list(msp.query("LWPOLYLINE[layer=='C-ROAD-ALIGN']")), \
        "road passes the plot but was not drawn"
    assert [e for e in msp.query("TEXT[layer=='C-ROAD-ALIGN']")], \
        "frontage label missing, so the architect cannot tell which edge fronts the road"


def test_a_long_road_does_not_drag_the_sheet_border_out(tmp_path):
    """A 100 km centreline must not become a 100 km sheet."""
    ezdxf = pytest.importorskip("ezdxf")
    out = tmp_path / "x.dxf"
    huge = [[[72.0, 18.96995], [73.5, 18.96995]]]
    dp.export_dxf(RING, PROPS, str(out), neighbors=[], roads=huge)
    coords = [c for e in ezdxf.readfile(str(out)).modelspace().query("LWPOLYLINE")
              for p in e.get_points("xy") for c in (p[0], p[1])]
    assert max(abs(c) for c in coords) < 1000


def test_text_extents_honours_alignment():
    """Regression, and a bug in the measuring helper itself: it read dxf.insert
    unconditionally, so the centred `CTS <n>` label measured half a width right and
    half a height high. Every collision verdict involving it was suspect."""
    ezdxf = pytest.importorskip("ezdxf")
    from ezdxf.enums import TextEntityAlignment
    msp = ezdxf.new("R2010").modelspace()

    centred = msp.add_text("CTS 1862", dxfattribs={"height": 2.0})
    centred.set_placement((0.0, 0.0), align=TextEntityAlignment.MIDDLE_CENTER)
    x0, y0, x1, y1 = dp.text_extents(centred)
    assert x0 < 0 < x1, "centred text must straddle its anchor horizontally"
    assert y0 < 0 < y1, "middle-aligned text must straddle its anchor vertically"
    assert x1 == pytest.approx(-x0, rel=1e-6)

    # Left/baseline is unchanged: box grows right and up from the insertion point.
    left = msp.add_text("CTS 1862", dxfattribs={"height": 2.0})
    left.set_placement((0.0, 0.0))
    lb = dp.text_extents(left)
    assert lb[0] == pytest.approx(0.0) and lb[1] == pytest.approx(0.0)


def test_text_extents_composes_alignment_with_rotation():
    ezdxf = pytest.importorskip("ezdxf")
    from ezdxf.enums import TextEntityAlignment
    msp = ezdxf.new("R2010").modelspace()
    e = msp.add_text("CTS 1862", dxfattribs={"height": 2.0, "rotation": 90.0})
    e.set_placement((0.0, 0.0), align=TextEntityAlignment.MIDDLE_CENTER)
    x0, y0, x1, y1 = dp.text_extents(e)
    # Rotated about its anchor, so it still straddles the origin, long axis vertical.
    assert x0 < 0 < x1 and y0 < 0 < y1
    assert (y1 - y0) > (x1 - x0)


def test_fit_label_to_width_budgets_against_the_plot():
    wide = dp.fit_label_to_width("ABUTTING ROAD: {}", "Bazar Road (9.15 M.)",
                                 max_width=200.0, char_h=1.0)
    assert wide == "ABUTTING ROAD: Bazar Road (9.15 M.)", "no truncation when it fits"

    tight = dp.fit_label_to_width("ABUTTING ROAD: {}", "Bazar Road (9.15 M.)",
                                  max_width=20.0, char_h=1.0)
    assert tight.endswith("...") and len(tight) < len(wide)

    # Never truncated to nothing: a label identifying nothing is worse than a long one.
    squeezed = dp.fit_label_to_width("ABUTTING ROAD: {}", "Jay Prakash Road Part II",
                                     max_width=0.5, char_h=1.0)
    assert "Jay Pras"[:4] in squeezed or len(squeezed) > len("ABUTTING ROAD: ")


def test_dimension_labels_prefer_the_longest_edges(tmp_path):
    """Where labels must compete for space, the dimensions an architect needs are
    the ones that keep their position."""
    ezdxf = pytest.importorskip("ezdxf")
    out = tmp_path / "x.dxf"
    # A long edge plus a run of near-collinear slivers, which is the DADAR-NAIGAON
    # 98 shape: its normals are nearly parallel, so nudging cannot separate them.
    ring = [[[72.8200, 18.9700], [72.8212, 18.9700],
             [72.82118, 18.970012], [72.82116, 18.970025], [72.82114, 18.970037],
             [72.8200, 18.9701], [72.8200, 18.9700]]]
    dp.export_dxf(ring, PROPS, str(out), neighbors=[])
    msp = ezdxf.readfile(str(out)).modelspace()
    labels = [e.dxf.text for e in msp.query("TEXT[layer=='C-ANNO-DIMS']")]
    lengths = sorted((float(t[:-1]) for t in labels), reverse=True)
    assert lengths, "no dimensions drawn at all"
    # The longest edge is ~127 m; it must never be the one sacrificed.
    assert lengths[0] > 50.0, f"the longest edge lost its label: {labels}"


def test_slivers_never_leave_overlapping_dimensions(tmp_path):
    """DADAR-NAIGAON 98 had seven mutual collisions among 1.07-1.34 m labels. A
    label that cannot be placed clear is dropped, not left unreadable."""
    ezdxf = pytest.importorskip("ezdxf")
    out = tmp_path / "x.dxf"
    ring = [[[72.8200, 18.9700], [72.8212, 18.9700],
             [72.82118, 18.970012], [72.82116, 18.970025], [72.82114, 18.970037],
             [72.82112, 18.970049], [72.8200, 18.9701], [72.8200, 18.9700]]]
    dp.export_dxf(ring, PROPS, str(out), neighbors=[])
    msp = ezdxf.readfile(str(out)).modelspace()
    boxes = [dp.text_extents(e) for e in msp.query("TEXT[layer=='C-ANNO-DIMS']")]
    boxes = [b for b in boxes if b]
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            assert not dp.boxes_overlap(a, b), "two dimension labels still overlap"


def test_centre_label_is_clear_of_boundary_dimensions(tmp_path):
    """'12.00m' landed on 'CTS 1862' because the centre label was placed last and
    never checked against anything."""
    ezdxf = pytest.importorskip("ezdxf")
    out = tmp_path / "x.dxf"
    # Long and thin, so the edge dimensions reach in toward the centroid.
    ring = [[[72.8200, 18.9700], [72.8215, 18.9700],
             [72.8215, 18.970055], [72.8200, 18.970055], [72.8200, 18.9700]]]
    dp.export_dxf(ring, dict(PROPS, cts_no="1862"), str(out), neighbors=[])
    msp = ezdxf.readfile(str(out)).modelspace()
    centre = [dp.text_extents(e) for e in msp.query("TEXT[layer=='C-ANNO-TEXT']")]
    dims = [dp.text_extents(e) for e in msp.query("TEXT[layer=='C-ANNO-DIMS']")]
    assert centre and centre[0]
    for d in dims:
        assert not dp.boxes_overlap(centre[0], d), "a dimension sits on the CTS label"


def test_setback_marker_and_road_label_do_not_collide(tmp_path):
    """Both stack below the plot at fixed offsets; on BANDRA-A 409 they overlapped."""
    ezdxf = pytest.importorskip("ezdxf")
    out = tmp_path / "x.dxf"
    # 8 x 16 m: too narrow for either setback, so both markers are emitted.
    ring = [[[72.8200, 18.9700], [72.820076, 18.9700],
             [72.820076, 18.970144], [72.8200, 18.970144], [72.8200, 18.9700]]]
    props = dict(PROPS, abutting_road="Bazar Road", road_width="9.15 M.")
    roads = [[[72.8195, 18.96995], [72.8206, 18.96995]]]
    dp.export_dxf(ring, props, str(out), neighbors=[], roads=roads)

    msp = ezdxf.readfile(str(out)).modelspace()
    below = []
    for layer in ("C-SETBACK-3M", "C-SETBACK-6M", "C-ROAD-ALIGN"):
        for e in msp.query(f"TEXT[layer=='{layer}']"):
            b = dp.text_extents(e)
            if b and b[1] < 0:          # below the plot, not a legend swatch label
                below.append((e.dxf.text, b))
    for i, (t1, b1) in enumerate(below):
        for t2, b2 in below[i + 1:]:
            assert not dp.boxes_overlap(b1, b2), f"{t1!r} overlaps {t2!r}"


def test_nearest_road_geoms_ranks_by_proximity_not_arrival_order():
    """Regression: `road_geoms[:6]` took the first six in arrival order. MCGM's road
    polygon layers return hundreds of rings per probe (552 for layer 44 at AMBIVALI
    807), so the frontage was pushed out of the slice -- the six that survived were
    910-2082 m away while the real frontage sat 8.7 m from the boundary."""
    ring = [[[72.8200, 18.9700], [72.8210, 18.9700],
             [72.8210, 18.9710], [72.8200, 18.9710], [72.8200, 18.9700]]]
    far = [[72.90, 19.05], [72.91, 19.06]]          # ~10 km away
    frontage = [[72.8205, 18.96999], [72.8206, 18.96999]]   # metres from the edge
    # Frontage arrives last, behind a wall of distant rings.
    geoms = [far] * 20 + [frontage]

    picked = dp.nearest_road_geoms(geoms, ring, limit=6)
    assert len(picked) == 6
    assert frontage in picked, "the nearest road must survive the cut"
    assert picked[0] is frontage, "the nearest road must rank first"


def test_nearest_road_geoms_survives_missing_geometry():
    ring = [[[72.8200, 18.9700], [72.8210, 18.9700], [72.8200, 18.9700]]]
    assert dp.nearest_road_geoms([], ring) == []
    assert dp.nearest_road_geoms([[[72.82, 18.97]]], []) == [[[72.82, 18.97]]]
