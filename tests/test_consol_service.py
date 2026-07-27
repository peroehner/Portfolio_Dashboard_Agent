"""Tests for author console footprint helpers."""

from services.consol_service import build_cache_health_snapshot, build_footprint_snapshot, process_memory
from services.worker_status import record_enrichment_warm, record_price_sync, worker_status_snapshot


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


def test_worker_status_records_cycles():
    record_price_sync(
        symbol_count=10,
        updated=8,
        new_alerts=1,
        refresh_targets=False,
    )
    record_enrichment_warm(queued=10, warmed=2, skipped=8, enabled=True)
    snap = worker_status_snapshot()
    assert snap["priceSync"]["symbolCount"] == 10
    assert snap["priceSync"]["source"] == "yahoo"
    assert snap["enrichmentWarm"]["warmed"] == 2
    assert snap["enrichmentWarm"]["skippedFresh"] == 8


def test_build_cache_health_snapshot_shape():
    snap = build_cache_health_snapshot()
    assert "workers" in snap
    assert "postgres" in snap
    assert "servingModel" in snap
    assert "prices" in snap["postgres"]
    assert "fundamentals" in snap["postgres"]
    assert "news" in snap["postgres"]
    assert "fresh" in snap["postgres"]["fundamentals"]
    assert "ttlSeconds" in snap["postgres"]["news"]
