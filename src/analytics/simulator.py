"""Data simulator: generates visitor events and daily active-user sets.

Everything is driven by a seeded ``random.Random`` so a run is reproducible.
"""

from __future__ import annotations

import random
from collections.abc import Iterator

from src.analytics.config import SimulationParams


def generate_visitor_events(params: SimulationParams) -> list[str]:
    """Return ``total_events`` user-id strings containing exactly ``unique_visitors`` distinct ids.

    Every id appears at least once and the remaining events are repeat visits
    drawn uniformly from the same ids, then the stream is shuffled so
    duplicates are interleaved the way real traffic would be.
    """
    rng = random.Random(params.seed)
    events = list(range(params.unique_visitors))
    repeats = params.total_events - params.unique_visitors
    events.extend(rng.randrange(params.unique_visitors) for _ in range(repeats))
    rng.shuffle(events)
    return [f"user:{uid}" for uid in events]


def batched(items: list, size: int) -> Iterator[list]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def generate_daily_active_users(
    params: SimulationParams, days: tuple[str, ...]
) -> dict[str, list[int]]:
    """Return ``{day: [integer user ids]}`` with guaranteed overlap between days.

    A fixed core of users is active every day; the rest of each day's users are
    sampled from the whole id space, so consecutive days also share some
    non-core users by chance. ids are integers because they become bit offsets.
    """
    rng = random.Random(params.seed + 1)
    id_space = range(1, params.user_id_space + 1)
    core = rng.sample(id_space, params.core_users)
    core_set = set(core)
    per_day_extra = params.daily_active_users - params.core_users

    result: dict[str, list[int]] = {}
    for day in days:
        extra: set[int] = set()
        while len(extra) < per_day_extra:
            need = per_day_extra - len(extra)
            extra.update(u for u in rng.sample(id_space, need) if u not in core_set)
        users = core + sorted(extra)
        rng.shuffle(users)
        result[day] = users
    return result
