import asyncio
from pathlib import Path

import pytest

from dp_lookup.application.contracts import ParcelContext
from dp_lookup.application.database_services import LocalDatabaseServices
from dp_lookup.application.local_spatial import LocalNeighbourProvider
from dp_lookup.application.snapshot_ingestion import SnapshotIngestionConfig
from dp_lookup.clients.local_parcels import LocalParcelError, LocalParcelFetcher, merge_local_features
from dp_lookup.clients.parcel_snapshot import (
    SnapshotCheckpoint,
    SnapshotFeature,
    SnapshotIngestionError,
    SnapshotIngestionResult,
    SnapshotManifest,
)
from dp_lookup.spatial_store import SnapshotStore


def feature(objectid, cts, x, *, village="WORLI", area=100.0):
    attrs = {
        "OBJECTID": objectid,
        "VILLAGE": village,
        "CTS_CS_NO": cts,
        "WARD": "G/S",
        "TYPE": "CTS",
        "AREA_APP_SQ_MTRS": area,
    }
    geometry = {
        "rings": [[[x, 0], [x + 10, 0], [x + 10, 10], [x, 10], [x, 0]]],
        "spatialReference": {"wkid": 102100},
    }
    return SnapshotFeature(objectid, attrs, geometry, {"attributes": attrs, "geometry": geometry})


def result(features, *, expected=None, missing=()):
    ids = tuple(item.object_id for item in features)
    expected_ids = tuple(expected or ids)
    manifest = SnapshotManifest(
        source_url="https://example.test/MapServer/13",
        layer_id=13,
        object_id_field="OBJECTID",
        requested_out_sr=102100,
        source_spatial_reference={"wkid": 102100},
        expected_ids=expected_ids,
        received_ids=ids,
        missing_ids=tuple(missing),
        duplicate_ids=(),
        rejected_ids=(),
        content_hash="abc123",
    )
    return SnapshotIngestionResult(
        tuple(features), manifest, SnapshotCheckpoint(expected_ids, ids)
    )


class ClientContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *_args):
        return None


class Importer:
    def __init__(self, snapshot_result):
        self.snapshot_result = snapshot_result

    async def __call__(self, _client, **_kwargs):
        return self.snapshot_result


def services(snapshot_result):
    return LocalDatabaseServices(
        importer=Importer(snapshot_result),
        client_factory=ClientContext,
        ingestion_config=SnapshotIngestionConfig(fetch_layer_metadata=True),
    )


def test_database_build_is_ready_then_explicitly_activated(tmp_path):
    database = tmp_path / "parcels.sqlite"
    admin = services(result([feature(1, "733", 0), feature(2, "734", 10)]))
    built = admin.build(database)
    assert built["state"] == "ready"
    assert built["records"] == 2
    assert admin.status(database)["active_snapshot_id"] is None

    activated = admin.activate(database)
    assert activated["state"] == "active"
    assert admin.verify(database)["ok"] is True


def test_incomplete_download_is_not_written(tmp_path):
    database = tmp_path / "parcels.sqlite"
    admin = services(result([feature(1, "733", 0)], expected=(1, 2), missing=(2,)))
    with pytest.raises(SnapshotIngestionError, match="not written"):
        admin.build(database)
    assert not database.exists()


def test_duplicate_cts_parts_are_combined_instead_of_first_feature_winning():
    rows = [
        {"objectid": 2, "area_app_sqm": None, "raw_attrs": feature(2, "9", 10).attributes,
         "geometry": feature(2, "9", 10).geometry},
        {"objectid": 1, "area_app_sqm": None, "raw_attrs": feature(1, "9", 0).attributes,
         "geometry": feature(1, "9", 0).geometry},
    ]
    merged = merge_local_features(rows)
    assert merged is not None
    assert merged["attributes"]["SOURCE_OBJECTIDS"] == [1, 2]
    assert merged["attributes"]["FEATURE_PART_COUNT"] == 2
    assert merged["attributes"]["SHAPE.AREA"] == pytest.approx(200)


def _active_database(path: Path):
    records = []
    for item in [feature(1, "733", 0), feature(2, "734", 10), feature(3, "735", 30)]:
        records.append({"objectid": item.object_id, "attributes": item.attributes, "geometry": item.geometry})
    with SnapshotStore.open(path) as store:
        snapshot = store.begin_snapshot(expected_count=3)
        store.insert_batch(snapshot, records)
        store.finalize_snapshot(snapshot)
        store.activate(snapshot)


def test_local_fetch_and_exact_spatial_neighbours(tmp_path):
    database = tmp_path / "parcels.sqlite"
    _active_database(database)
    fetched = asyncio.run(LocalParcelFetcher(database)(object(), "WORLI", "733"))
    assert fetched["attributes"]["_DP_PARCEL_SOURCE"] == "local_snapshot"

    parcel = ParcelContext(
        village="WORLI",
        cts_no="733",
        attrs=fetched["attributes"],
        rings=fetched["geometry"]["rings"],
        wgs_rings=[],
        area_sqm=100,
        area_source="approved",
        latitude=0,
        longitude=0,
        cx=5,
        cy=5,
        mcx=5,
        mcy=5,
        xs=[0, 10],
        ys=[0, 10],
        window_radius=50,
    )
    neighbours = LocalNeighbourProvider(database)(parcel)
    assert neighbours.method == "spatial_database"
    assert [item["cts_no"] for item in neighbours.plots] == ["734"]
    assert neighbours.plots[0]["shared_boundary_m"] == pytest.approx(10)


def test_local_only_missing_database_is_explicit(tmp_path):
    with pytest.raises(LocalParcelError, match="does not exist"):
        asyncio.run(LocalParcelFetcher(tmp_path / "missing.sqlite")(object(), "WORLI", "733"))
