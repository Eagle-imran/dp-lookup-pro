"""Focused tests for the cache's persistence and concurrency safeguards."""

import json
import multiprocessing
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import dp_lookup.clients.cache as cache


def _child_cache_writer(args):
    output, key, artifact = args
    # Import inside the child so this also exercises independent process
    # state rather than inheriting the parent's _STORES mapping.
    from dp_lookup.clients import cache as child_cache

    child_cache.write_cache_entry(
        output,
        key,
        {"metadata": {}, "export_files": {"bundle": artifact}},
    )


def _result(tmp_path, name="bundle.pdf"):
    bundle = tmp_path / name
    bundle.write_text("bundle", encoding="utf-8")
    return {"metadata": {}, "export_files": {"bundle": str(bundle)}}


def test_cache_path_canonicalizes_aliases(tmp_path):
    cache._STORES.clear()
    output = tmp_path / "reports"
    alias = output / ".." / "reports"
    assert cache.cache_path_for(str(output)) == cache.cache_path_for(str(alias))


def test_new_writes_include_metadata_and_legacy_timestamped_entries_remain_readable(tmp_path):
    cache._STORES.clear()
    output = str(tmp_path)
    cache.write_cache_entry(output, "NEW", _result(tmp_path, "new.pdf"))

    with open(cache.cache_path_for(output), "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    assert payload[cache.CACHE_METADATA_KEY] == {
        "schema_version": cache.CACHE_SCHEMA_VERSION,
        "app_version": cache.CACHE_APP_VERSION,
    }
    assert payload["NEW"]["cache_schema_version"] == cache.CACHE_SCHEMA_VERSION
    assert payload["NEW"]["application_version"] == cache.CACHE_APP_VERSION

    legacy = _result(tmp_path, "legacy.pdf")
    payload = {"OLD": {"cached_at": 1_700_000_000, "result": legacy}}
    with open(cache.cache_path_for(output), "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    cache._STORES.clear()
    assert cache.read_cache_entry(output, "OLD", ttl_seconds=-1) is not None


def test_known_incompatible_entry_schema_is_not_served(tmp_path):
    cache._STORES.clear()
    output = str(tmp_path)
    path = cache.cache_path_for(output)
    payload = {
        "FUTURE": {
            "cached_at": 1_900_000_000,
            "cache_schema_version": cache.CACHE_SCHEMA_VERSION + 1,
            "application_version": "future",
            "result": _result(tmp_path, "future.pdf"),
        }
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)

    assert cache.read_cache_entry(output, "FUTURE", ttl_seconds=-1) is None


def test_nonfinite_and_future_timestamps_are_not_served(tmp_path):
    cache._STORES.clear()
    output = str(tmp_path)
    artifact = _result(tmp_path, "timestamp.pdf")
    path = cache.cache_path_for(output)

    for value in (float("nan"), float("inf"), float("-inf"), 2_000_000_000):
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"K": {"cached_at": value, "result": artifact}}, handle, allow_nan=True)
        cache._STORES.clear()
        assert cache.read_cache_entry(output, "K", ttl_seconds=-1) is None


def test_bundle_requires_regular_nonempty_files(tmp_path):
    directory = tmp_path / "bundle-dir"
    directory.mkdir()
    empty = tmp_path / "empty.pdf"
    empty.touch()
    good = tmp_path / "good.pdf"
    good.write_bytes(b"x")

    assert cache.bundle_is_intact({"export_files": {"bundle": str(directory)}}) is False
    assert cache.bundle_is_intact({"export_files": {"bundle": str(empty)}}) is False
    assert cache.bundle_is_intact({"export_files": {"bundle": str(good)}}) is True


def test_real_manifest_accepts_bundle_directory_but_requires_its_files(tmp_path):
    bundle = tmp_path / "plot"
    bundle.mkdir()
    report = bundle / "report.pdf"
    report.write_bytes(b"%PDF")
    result = {
        "export_files": {
            "bundle_folder": str(bundle),
            "pdf_report": str(report),
            "master_excel_register": str(tmp_path / "shared.xlsx"),
        }
    }

    assert cache.bundle_is_intact(result) is True
    report.unlink()
    assert cache.bundle_is_intact(result) is False


def test_atomic_write_failure_preserves_previous_cache(tmp_path, monkeypatch):
    cache._STORES.clear()
    output = str(tmp_path)
    cache.write_cache_entry(output, "FIRST", _result(tmp_path, "first.pdf"))
    path = cache.cache_path_for(output)
    before = open(path, "rb").read()
    previous_store = cache._STORES[path]

    def fail_replace(_source, _target):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(cache.os, "replace", fail_replace)
    cache.write_cache_entry(output, "SECOND", _result(tmp_path, "second.pdf"))
    assert open(path, "rb").read() == before
    assert cache._STORES[path] is previous_store
    assert cache.read_cache_entry(output, "SECOND", ttl_seconds=-1) is None
    assert not [name for name in os.listdir(tmp_path) if name.endswith(".tmp")]


def test_concurrent_writers_keep_all_distinct_entries(tmp_path):
    cache._STORES.clear()
    output = str(tmp_path)

    def write(index):
        cache.write_cache_entry(output, f"KEY-{index}", _result(tmp_path, f"bundle-{index}.pdf"))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, range(20)))

    with open(cache.cache_path_for(output), "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    assert all(f"KEY-{index}" in payload for index in range(20))


def test_multiprocess_writers_keep_all_distinct_entries(tmp_path):
    cache._STORES.clear()
    output = str(tmp_path)
    artifact = str(Path(tmp_path) / "shared.pdf")
    Path(artifact).write_bytes(b"bundle")
    jobs = [(output, f"PROCESS-{index}", artifact) for index in range(12)]

    context = multiprocessing.get_context("spawn")
    with context.Pool(processes=4) as pool:
        pool.map(_child_cache_writer, jobs)

    with open(cache.cache_path_for(output), "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    assert all(f"PROCESS-{index}" in payload for index in range(12))
