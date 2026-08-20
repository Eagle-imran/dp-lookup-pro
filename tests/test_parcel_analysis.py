import pytest

from dp_lookup.core.parcel_analysis import (
    ParcelGeometryRecord,
    SearchCriteria,
    amalgamate,
    filter_parcels,
    find_adjacent,
)


def parcel(i, x, area=100, village="WORLI"):
    return ParcelGeometryRecord(i, village, str(i), area, [[[x, 0], [x + 10, 0], [x + 10, 10], [x, 10], [x, 0]]])


def test_shared_edge_and_tolerance_gap_and_exclusion():
    subject = parcel(1, 0)
    result = find_adjacent(subject, [subject, parcel(2, 10), parcel(3, 10.3), parcel(4, 15)])
    assert [r.candidate_objectid for r in result] == [2, 3]
    assert result[0].exact_touch and result[0].shared_boundary_m == pytest.approx(10)
    assert result[1].tolerance_gap and result[1].gap_m == pytest.approx(0.3)

    # A corner-only touch and an overlap are data-quality relationships, not
    # a shared cadastral edge or a disclosed tolerance gap.
    corner = ParcelGeometryRecord(5, "WORLI", "5", 10, [[[10, 10], [20, 10], [20, 20], [10, 20], [10, 10]]])
    overlap = ParcelGeometryRecord(6, "WORLI", "6", 10, [[[5, 0], [15, 0], [15, 10], [5, 10], [5, 0]]])
    assert find_adjacent(subject, [corner, overlap]) == ()


def test_holes_and_multipart_union_area():
    rings = [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]], [[2, 2], [2, 4], [4, 4], [4, 2], [2, 2]], [[20, 0], [22, 0], [22, 2], [20, 2], [20, 0]]]
    result = amalgamate([ParcelGeometryRecord(9, "W", "9", 0, rings)])
    assert result.area_sqm == pytest.approx(100 - 4 + 4)


def test_amalgamate_combined_area_and_validation():
    result = amalgamate([parcel(2, 10), parcel(1, 0)])
    assert result.area_sqm == pytest.approx(200)
    assert result.member_objectids == (1, 2)
    with pytest.raises(ValueError):
        amalgamate([])


def test_filter_official_area_and_stable_sort():
    records = [parcel(3, 0, 30), parcel(1, 0, 100), parcel(2, 0, 50, "COLABA")]
    found = filter_parcels(records, SearchCriteria(village="worli", min_area_sqm=40, max_area_sqm=110))
    assert [r.objectid for r in found] == [1]
    assert [r.objectid for r in filter_parcels(records, SearchCriteria(ward="A"), wards={1: "A", 2: "B", 3: "A"})] == [1, 3]
