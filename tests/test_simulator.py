from dataclasses import replace

import pytest

from src.analytics import config
from src.analytics.simulator import batched, generate_daily_active_users, generate_visitor_events

P = replace(config.SimulationParams(), total_events=2000, unique_visitors=700, user_id_space=3000,
            daily_active_users=400, core_users=150)


def test_visitor_events_have_exact_unique_count_and_duplicates():
    events = generate_visitor_events(P)
    assert len(events) == 2000
    assert len(set(events)) == 700
    assert len(events) > len(set(events))


def test_visitor_events_are_reproducible_and_seed_sensitive():
    assert generate_visitor_events(P) == generate_visitor_events(P)
    assert generate_visitor_events(P) != generate_visitor_events(replace(P, seed=7))


def test_daily_users_are_integers_unique_per_day_and_overlap():
    daily = generate_daily_active_users(P, config.DAYS)
    assert tuple(daily) == config.DAYS and len(daily) == 7
    for users in daily.values():
        assert len(users) == len(set(users)) == 400
        assert all(isinstance(u, int) and 1 <= u <= 3000 for u in users)
    days = list(daily.values())
    assert len(set(days[0]) & set(days[1])) >= 150  # the core is shared every day
    assert len(set.intersection(*map(set, days))) >= 150


def test_days_are_seven_consecutive_ending_on_the_hll_day():
    assert config.DAYS[0] == "2024-10-20" and config.DAYS[-1] == "2024-10-26"
    assert config.HLL_DAY == config.DAU_DATE
    assert config.DAU_KEYS[0] == "dau:2024-10-20" and config.WAU_KEY == "wau:2024-w43"
    assert config.HLL_KEY == "visitors:daily:2024-10-26"


@pytest.mark.parametrize("kwargs", [
    {"total_events": 5, "unique_visitors": 10},
    {"core_users": 500, "daily_active_users": 100},
    {"daily_active_users": 10**7},
    {"batch_size": 0},
])
def test_invalid_params_rejected(kwargs):
    with pytest.raises(ValueError):
        replace(config.SimulationParams(), **kwargs).validate()


def test_batched_covers_everything_once():
    assert [len(b) for b in batched(list(range(25)), 10)] == [10, 10, 5]
