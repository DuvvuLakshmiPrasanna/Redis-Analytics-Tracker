"""Part 2: daily and weekly active users with Bitmaps, compared with a Redis Set."""

from __future__ import annotations

import logging
from typing import Any

import redis

from src.analytics import config
from src.analytics.redis_client import memory_usage
from src.analytics.simulator import batched

log = logging.getLogger("analytics.bitmap")


def run_bitmap_analysis(
    client: redis.Redis,
    daily_users: dict[str, list[int]],
    params: config.SimulationParams,
) -> dict[str, Any]:
    """Record 7 days of activity with SETBIT, union them with BITOP OR, and measure."""
    if tuple(daily_users) != config.DAYS:
        raise ValueError(f"daily_users must cover exactly these days, in order: {config.DAYS}")

    client.delete(*config.DAU_KEYS, config.WAU_KEY, config.DAU_EXACT_SET_KEY)

    # Track daily active users: one bitmap per day, user id == bit offset.
    for day, key in zip(config.DAYS, config.DAU_KEYS, strict=True):
        for batch in batched(daily_users[day], params.batch_size):
            pipe = client.pipeline(transaction=False)
            for user_id in batch:
                pipe.setbit(key, user_id, 1)
            pipe.execute()
        log.info("SETBIT %s: %d users set", key, len(daily_users[day]))

    # Weekly active users: a bit is 1 if the user was active on at least one day.
    client.bitop("OR", config.WAU_KEY, *config.DAU_KEYS)
    log.info("BITOP OR %s <- %s", config.WAU_KEY, ", ".join(config.DAU_KEYS))

    dau_count = int(client.bitcount(config.DAU_KEY))
    wau_count = int(client.bitcount(config.WAU_KEY))
    log.info("BITCOUNT %s -> %d", config.DAU_KEY, dau_count)
    log.info("BITCOUNT %s -> %d", config.WAU_KEY, wau_count)

    # Bitmaps are exact, so they must match the ground truth held in this script.
    expected_dau = len(set(daily_users[config.DAU_DATE]))
    expected_wau = len(set().union(*(set(users) for users in daily_users.values())))
    if (dau_count, wau_count) != (expected_dau, expected_wau):
        raise RuntimeError(
            f"bitmap counts wrong: DAU {dau_count} vs {expected_dau}, "
            f"WAU {wau_count} vs {expected_wau}"
        )

    # Comparison: the same day's users stored in a plain Redis Set.
    for batch in batched(daily_users[config.DAU_DATE], params.batch_size):
        client.sadd(config.DAU_EXACT_SET_KEY, *batch)
    log.info("SADD %s: %d users", config.DAU_EXACT_SET_KEY, expected_dau)

    return {
        "dau_date": config.DAU_DATE,
        "dau_count": dau_count,
        "wau_period": config.WAU_PERIOD,
        "wau_count": wau_count,
        "bitmap_memory_per_day_bytes": memory_usage(client, config.DAU_KEY),
        "set_memory_for_dau_bytes": memory_usage(client, config.DAU_EXACT_SET_KEY),
    }
