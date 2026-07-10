"""Tests for author console footprint helpers."""

from services.consol_service import build_footprint_snapshot, process_memory


def test_process_memory_returns_rss():
    mem = process_memory()
    assert "rssMb" in mem
    if mem["rssMb"] is not None:
        assert mem["rssMb"] > 0


def test_build_footprint_snapshot_shape():
    snap = build_footprint_snapshot()
    assert "process" in snap
    assert "database" in snap
    assert "caches" in snap
    assert isinstance(snap["database"]["categories"], list)
    assert isinstance(snap["caches"]["categories"], list)
    db_keys = {row["key"] for row in snap["database"]["categories"]}
    assert "notes" in db_keys
    assert "agent_reads" in db_keys
    assert "shared_sai" in db_keys
    cache_keys = {row["key"] for row in snap["caches"]["categories"]}
    assert "ticker_info" in cache_keys
    assert "fib_levels" in cache_keys
    assert "ttlSeconds" in snap["caches"]["categories"][0]
    assert isinstance(snap["caches"].get("historyBySymbol"), list)
