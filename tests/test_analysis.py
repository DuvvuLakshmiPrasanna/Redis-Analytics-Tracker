"""Integration tests against a real Redis server."""

from dataclasses import replace

import pytest

from src.analytics import config
from src.analytics.bitmap import run_bitmap_analysis
from src.analytics.hll import error_rate_percentage, run_hll_analysis
from src.analytics.simulator import generate_daily_active_users, generate_visitor_events

P = replace(config.SimulationParams(), total_events=20000, unique_visitors=8000, user_id_space=20000,
            daily_active_users=3000, core_users=1000, batch_size=2500)


def test_error_rate_formula():
    assert error_rate_percentage(101, 100) == pytest.approx(1.0)
    assert error_rate_percentage(99, 100) == pytest.approx(-1.0)
    assert isinstance(error_rate_percentage(100, 100), float)
    with pytest.raises(ValueError):
        error_rate_percentage(1, 0)


def test_hll_report_and_keys(redis_client):
    report = run_hll_analysis(redis_client, generate_visitor_events(P), P)
    assert redis_client.exists(config.HLL_KEY) == 1
    assert redis_client.type(config.HLL_KEY) == b"string"  # Redis stores an HLL as a string
    assert redis_client.exists(config.HLL_EXACT_SET_KEY) == 1
    assert report["true_unique_count"] == 8000
    assert abs(report["error_rate_percentage"]) < 5  # loose: tiny sets, not the 0.81% regime
    expected = (report["hll_unique_count"] - 8000) / 8000 * 100
    assert report["error_rate_percentage"] == pytest.approx(expected, abs=1e-9)
    assert report["hll_memory_usage_bytes"] > 0 and report["set_memory_usage_bytes"] > 0
    assert report["set_memory_usage_bytes"] > report["hll_memory_usage_bytes"]


def test_hll_rerun_does_not_accumulate(redis_client):
    first = run_hll_analysis(redis_client, generate_visitor_events(P), P)
    second = run_hll_analysis(redis_client, generate_visitor_events(P), P)
    assert first["hll_unique_count"] == second["hll_unique_count"]
    assert second["true_unique_count"] == 8000


def test_bitmaps_dau_wau_are_exact_and_keys_exist(redis_client):
    daily = generate_daily_active_users(P, config.DAYS)
    report = run_bitmap_analysis(redis_client, daily, P)
    for key in (*config.DAU_KEYS, config.WAU_KEY):
        assert redis_client.exists(key) == 1, key
    assert len(config.DAU_KEYS) == 7
    assert report["dau_count"] == 3000
    assert report["wau_count"] == len(set().union(*map(set, daily.values())))
    assert report["wau_count"] >= report["dau_count"]
    assert report["wau_period"] == "2024-w43" and report["dau_date"] == "2024-10-26"
    assert report["bitmap_memory_per_day_bytes"] > 0 and report["set_memory_for_dau_bytes"] > 0


def test_wau_equals_or_of_days_and_and_cohort_is_subset(redis_client):
    daily = generate_daily_active_users(P, config.DAYS)
    run_bitmap_analysis(redis_client, daily, P)
    redis_client.bitop("AND", "scratch:all7", *config.DAU_KEYS)
    try:
        assert redis_client.bitcount("scratch:all7") == len(set.intersection(*map(set, daily.values())))
        assert redis_client.bitcount("scratch:all7") >= P.core_users
    finally:
        redis_client.delete("scratch:all7")
    for user in list(daily[config.DAYS[0]])[:50]:
        assert redis_client.getbit(config.WAU_KEY, user) == 1


def test_bitmap_rejects_wrong_days(redis_client):
    with pytest.raises(ValueError):
        run_bitmap_analysis(redis_client, {"2024-10-26": [1]}, P)
