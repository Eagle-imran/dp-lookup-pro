"""Integration contract between the downloader and planning SQLite store."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from dp_lookup.application import planning_database_services as service_module
from dp_lookup.application.planning_database_services import LocalPlanningDatabaseServices
from dp_lookup.application.planning_snapshot import (
    PlanningFeature,
    PlanningLayerCheckpoint,
    PlanningLayerManifest,
    PlanningSnapshotCheckpoint,
    PlanningSnapshotError,
    PlanningSnapshotManifest,
    PlanningSnapshotResult,
    planning_registry_hash,
)
from dp_lookup.planning_snapshot import PlanningSnapshotStore


class _ClientContext:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *_args: Any) -> None:
        return None


async def _complete_importer(_client: Any, **kwargs: Any) -> PlanningSnapshotResult:
    specs = tuple(kwargs["specs"])
    object_id = int(kwargs.get("fixture_object_id", 1))
    manifests = []
    checkpoints = []
    for spec in specs:
        await kwargs["on_inventory"](
            spec,
            (object_id,),
            {
                "source_url": f"fixture://{spec.layer_id}",
                "layer_metadata": {"geometryType": spec.geometry_type},
            },
        )
        geometry = (
            {"paths": [[[0, 0], [10, 10]]]}
            if spec.geometry_type == "esriGeometryPolyline"
            else {"rings": [[[0, 0], [10, 0], [10, 10], [0, 0]]]}
        )
        attributes = {spec.object_id_field: object_id}
        raw = {"attributes": attributes, "geometry": geometry}
        await kwargs["on_batch"](
            spec,
            (PlanningFeature(spec.layer_id, object_id, attributes, geometry, raw),),
        )
        manifests.append(
            PlanningLayerManifest(
                layer_id=spec.layer_id,
                name=spec.name,
                source_url=f"fixture://{spec.layer_id}",
                object_id_field=spec.object_id_field,
                geometry_type=spec.geometry_type,
                out_fields=("*",),
                expected_ids=(object_id,),
                received_ids=(object_id,),
                missing_ids=(),
                content_hash=f"hash-{spec.layer_id}",
            )
        )
        checkpoints.append(PlanningLayerCheckpoint(spec.layer_id, (object_id,), (object_id,)))
    ids = tuple(spec.layer_id for spec in specs)
    manifest = PlanningSnapshotManifest(
        service_url="fixture://planning",
        registry_layer_ids=ids,
        layers=tuple(manifests),
        registry_hash=planning_registry_hash(specs),
    )
    return PlanningSnapshotResult(
        (),
        manifest,
        PlanningSnapshotCheckpoint(tuple(checkpoints), ids),
    )


def test_build_verify_and_activate_complete_planning_snapshot(tmp_path: Path):
    database = tmp_path / "mcgm.sqlite"
    services = LocalPlanningDatabaseServices(
        importer=_complete_importer,
        client_factory=_ClientContext,
    )

    built = services.build_planning(database, {})

    assert built["state"] == "ready"
    assert built["layers"] > 40
    assert built["records"] == built["layers"]
    assert Path(str(built["manifest"])).is_file()
    verified = services.verify_planning(database, {})
    assert verified["ok"] is True
    activated = services.activate_planning(database, {})
    assert activated["state"] == "active"
    with PlanningSnapshotStore.open(database) as store:
        assert store.active_snapshot_id() == built["snapshot_id"]


def test_missing_status_and_incomplete_build_remain_safe_and_resumable(tmp_path: Path):
    database = tmp_path / "mcgm.sqlite"
    services = LocalPlanningDatabaseServices(client_factory=_ClientContext)
    assert services.status_planning(database, {})["exists"] is False
    with pytest.raises(RuntimeError, match="does not exist"):
        services.verify_planning(database, {})

    async def incomplete(_client: Any, **kwargs: Any) -> PlanningSnapshotResult:
        specs = tuple(kwargs["specs"])
        first = specs[0]
        await kwargs["on_inventory"](first, (1, 2), {"object_id_field": first.object_id_field})
        geometry = {"rings": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}
        attrs = {first.object_id_field: 1}
        raw = {"attributes": attrs, "geometry": geometry}
        await kwargs["on_batch"](first, (PlanningFeature(first.layer_id, 1, attrs, geometry, raw),))
        layer = PlanningLayerManifest(
            first.layer_id,
            first.name,
            "fixture://partial",
            first.object_id_field,
            first.geometry_type,
            first.out_fields,
            (1, 2),
            (1,),
            (2,),
        )
        ids = tuple(spec.layer_id for spec in specs)
        return PlanningSnapshotResult(
            (),
            PlanningSnapshotManifest("fixture://partial", ids, (layer,), registry_hash=planning_registry_hash(specs)),
            PlanningSnapshotCheckpoint((PlanningLayerCheckpoint(first.layer_id, (1, 2), (1,)),), ids),
        )

    partial_services = LocalPlanningDatabaseServices(importer=incomplete, client_factory=_ClientContext)
    with pytest.raises(PlanningSnapshotError, match="remains resumable"):
        partial_services.build_planning(database, {})
    status = partial_services.status_planning(database, {})
    assert status["snapshots"][-1]["state"] == "building"
    with pytest.raises(RuntimeError, match="no ready planning snapshot"):
        partial_services.activate_planning(database, {})


def test_activation_idempotence_second_version_and_rollback(tmp_path: Path):
    database = tmp_path / "mcgm.sqlite"
    services = LocalPlanningDatabaseServices(importer=_complete_importer, client_factory=_ClientContext)
    first = services.build_planning(database, {})
    services.activate_planning(database, {})
    assert services.activate_planning(database, {}) == {
        "snapshot_id": first["snapshot_id"],
        "state": "active",
        "changed": False,
    }

    second = services.build_planning(database, {})
    assert services.verify_planning(database, {})["snapshot_id"] == second["snapshot_id"]
    assert services.activate_planning(database, {})["snapshot_id"] == second["snapshot_id"]
    assert services.rollback_planning(database, {})["snapshot_id"] == first["snapshot_id"]
    assert services.status_planning(database, {})["active_snapshot_id"] == first["snapshot_id"]


def test_checkpoint_helpers_and_atomic_write_fail_closed(tmp_path: Path, monkeypatch):
    database = tmp_path / "db.sqlite"
    assert service_module._checkpoint_path(database, None).name.endswith(".planning.checkpoint.json")
    assert service_module._manifest_path(database, "custom.json") == Path("custom.json")
    assert service_module._load_checkpoint(tmp_path / "missing.json") is None

    valid = tmp_path / "valid.json"
    valid.write_text('{"registry_layer_ids": [], "layers": []}', encoding="utf-8")
    loaded = service_module._load_checkpoint(valid)
    assert loaded is not None and loaded.layers == () and loaded.registry_layer_ids == ()

    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    with pytest.raises(PlanningSnapshotError, match="unreadable"):
        service_module._load_checkpoint(broken)
    broken.write_text("[]", encoding="utf-8")
    with pytest.raises(PlanningSnapshotError, match="not a JSON object"):
        service_module._load_checkpoint(broken)

    target = tmp_path / "atomic.json"

    def fail_replace(*_args):
        raise OSError("replace denied")

    monkeypatch.setattr(service_module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace denied"):
        service_module._atomic_json_write(target, {"safe": True})
    assert not list(tmp_path.glob(".atomic.json.*.tmp"))


@pytest.mark.parametrize(
    "message,expected_state",
    [("different inventory at source", "failed"), ("temporary outage", "building")],
)
def test_build_failure_state_depends_on_inventory_safety(tmp_path: Path, message: str, expected_state: str):
    async def fail_importer(_client: Any, **_kwargs: Any) -> PlanningSnapshotResult:
        raise PlanningSnapshotError(message)

    database = tmp_path / f"{expected_state}.sqlite"
    services = LocalPlanningDatabaseServices(importer=fail_importer, client_factory=_ClientContext)
    with pytest.raises(PlanningSnapshotError, match=message):
        services.build_planning(database, {})
    assert services.status_planning(database, {})["snapshots"][-1]["state"] == expected_state


async def _incremental_check(_client: Any, database: Path, *, changed=(81,), revision=1):
    with closing(sqlite3.connect(database)) as connection:
        base_id = connection.execute("SELECT snapshot_id FROM planning_snapshots WHERE state='active'").fetchone()[0]
    return {
        "checked_at": "fixture-time",
        "planning": {
            "layers": [
                {
                    "canonical_layer_id": spec.layer_id,
                    "local": {"snapshot_id": base_id},
                    "status": "changed" if spec.layer_id in changed else "unchanged",
                    "upstream": {
                        "record_count": 1,
                        "inventory_hash": f"inventory-{spec.layer_id}",
                        "metadata_hash": "schema",
                        "max_last_edited_date": revision,
                    },
                }
                for spec in service_module.canonical_planning_specs()
            ]
        },
    }


def _active_fixture(database):
    services = LocalPlanningDatabaseServices(importer=_complete_importer, client_factory=_ClientContext)
    first = services.build_planning(database, {})
    services.activate_planning(database, {})
    return first


def test_incremental_refresh_downloads_only_selected_layers_and_preserves_the_rest(tmp_path):
    database = tmp_path / "incremental.sqlite"
    first = _active_fixture(database)
    seen = []

    async def fetch_selected(client, **kwargs):
        seen.extend(spec.layer_id for spec in kwargs["specs"])
        return await _complete_importer(client, fixture_object_id=2, **kwargs)

    services = LocalPlanningDatabaseServices(
        importer=fetch_selected,
        client_factory=_ClientContext,
        upstream_checker=_incremental_check,
    )
    result = services.build_planning(database, {"layer_ids": (81,)})
    assert seen == [81]
    assert result["state"] == "ready"
    assert result["base_snapshot_id"] == first["snapshot_id"]
    assert result["fetched_records"] == 1
    assert result["layers"] == first["layers"]
    with PlanningSnapshotStore.open(database) as store:
        assert store.active_snapshot_id() == first["snapshot_id"]
        assert store.object_ids(result["snapshot_id"], 81) == (2,)
        assert store.object_ids(result["snapshot_id"], 0) == (1,)
        assert store.object_ids(first["snapshot_id"], 81) == (1,)
        inherited = store.layer_snapshot(result["snapshot_id"], 0)
        assert inherited.metadata["inherited_from_snapshot_id"] == first["snapshot_id"]
        assert inherited.content_hash == store.layer_snapshot(first["snapshot_id"], 0).content_hash
        assert store.features_in_bbox(0, -1, 20, -1, 20, snapshot_id=result["snapshot_id"])
    assert services.verify_planning(database, {})["ok"]
    assert services.activate_planning(database, {})["snapshot_id"] == result["snapshot_id"]
    assert services.rollback_planning(database, {})["snapshot_id"] == first["snapshot_id"]


def test_incremental_refresh_rejects_omitted_changes_without_staging(tmp_path):
    database = tmp_path / "omitted.sqlite"
    _active_fixture(database)

    async def check(client, path):
        return await _incremental_check(client, path, changed=(81, 85))

    services = LocalPlanningDatabaseServices(client_factory=_ClientContext, upstream_checker=check)
    with pytest.raises(PlanningSnapshotError, match="85 also changed"):
        services.build_planning(database, {"layer_ids": (81,)})
    assert len(services.status_planning(database, {})["snapshots"]) == 1


def test_incremental_refresh_fails_on_source_drift_and_keeps_active_data(tmp_path):
    database = tmp_path / "drift.sqlite"
    first = _active_fixture(database)
    calls = 0

    async def check(client, path):
        nonlocal calls
        calls += 1
        return await _incremental_check(client, path, revision=calls)

    services = LocalPlanningDatabaseServices(
        importer=_complete_importer,
        client_factory=_ClientContext,
        upstream_checker=check,
    )
    with pytest.raises(PlanningSnapshotError, match="upstream changed during"):
        services.build_planning(database, {"layer_ids": (81,)})
    status = services.status_planning(database, {})
    assert status["active_snapshot_id"] == first["snapshot_id"]
    assert status["snapshots"][-1]["state"] == "failed"


def test_incremental_resume_is_separate_from_full_build_and_checks_original_fingerprint(tmp_path):
    database = tmp_path / "resume.sqlite"
    _active_fixture(database)
    registry_hash = planning_registry_hash(service_module.canonical_planning_specs())
    with PlanningSnapshotStore.open(database) as store:
        full_id = store.begin_snapshot(metadata={"registry_hash": registry_hash})

    async def unavailable(_client, **_kwargs):
        raise RuntimeError("temporary outage")

    services = LocalPlanningDatabaseServices(
        importer=unavailable,
        client_factory=_ClientContext,
        upstream_checker=_incremental_check,
    )
    with pytest.raises(RuntimeError, match="temporary outage"):
        services.build_planning(database, {"layer_ids": (81,)})
    with PlanningSnapshotStore.open(database) as store:
        partial_id = store.status()["snapshots"][-1]["snapshot_id"]
        assert partial_id != full_id
        assert store.find_resumable_snapshot(registry_hash) == full_id

    services.importer = _complete_importer
    result = services.build_planning(database, {"layer_ids": (81,)})
    assert result["snapshot_id"] == partial_id
    assert result["resumed"] is True

    services.importer = unavailable
    with pytest.raises(RuntimeError):
        services.build_planning(database, {"layer_ids": (81,)})

    async def drift(client, path):
        return await _incremental_check(client, path, revision=2)

    services.upstream_checker = drift
    with pytest.raises(PlanningSnapshotError, match="upstream changed since"):
        services.build_planning(database, {"layer_ids": (81,)})
    assert services.status_planning(database, {})["snapshots"][-1]["state"] == "failed"


@pytest.mark.parametrize("layers", [(), (13,), (99999,)])
def test_incremental_refresh_requires_an_existing_complete_baseline_and_valid_selection(tmp_path, layers):
    database = tmp_path / "missing.sqlite"
    services = LocalPlanningDatabaseServices(client_factory=_ClientContext)
    with pytest.raises(PlanningSnapshotError, match="existing active"):
        services.build_planning(database, {"layer_ids": layers})
    assert not database.exists()
    _active_fixture(database)
    with pytest.raises(PlanningSnapshotError, match="--layers must select"):
        services.build_planning(database, {"layer_ids": layers})
