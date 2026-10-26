"""Part 1: unique visitors with HyperLogLog, compared with an exact Redis Set."""

from __future__ import annotations

import logging
from typing import Any

import redis

from src.analytics import config
from src.analytics.redis_client import memory_usage
from src.analytics.simulator import batched

log = logging.getLogger("analytics.hll")


def error_rate_percentage(estimate: int, truth: int) -> float:
    """``((hll_count - true_count) / true_count) * 100`` as a float."""
    if truth <= 0:
        raise ValueError("true_count must be positive")
    return float(((estimate - truth) / truth) * 100)


def run_hll_analysis(
    client: redis.Redis, events: list[str], params: config.SimulationParams
) -> dict[str, Any]:
    """Feed ``events`` to a HyperLogLog and a Set, then compare count and memory."""
    client.delete(config.HLL_KEY, config.HLL_EXACT_SET_KEY)  # make re-runs start clean

    true_unique: set[str] = set()  # exact count, kept inside this script
    for batch in batched(events, params.batch_size):
        pipe = client.pipeline(transaction=False)
        pipe.pfadd(config.HLL_KEY, *batch)
        pipe.sadd(config.HLL_EXACT_SET_KEY, *batch)
        pipe.execute()
        true_unique.update(batch)
    log.info("PFADD %s: %d events sent", config.HLL_KEY, len(events))
    log.info("SADD %s: %d events sent", config.HLL_EXACT_SET_KEY, len(events))

    hll_count = int(client.pfcount(config.HLL_KEY))
    log.info("PFCOUNT %s -> %d", config.HLL_KEY, hll_count)
    true_count = len(true_unique)

    # The Redis Set is a second, independent exact count: it must agree with the local set.
    redis_set_count = int(client.scard(config.HLL_EXACT_SET_KEY))
    if redis_set_count != true_count:
        raise RuntimeError(
            f"exact counts disagree: local set={true_count}, Redis set={redis_set_count}"
        )

    return {
        "day": config.HLL_DAY,
        "true_unique_count": true_count,
        "hll_unique_count": hll_count,
        "error_rate_percentage": error_rate_percentage(hll_count, true_count),
        "hll_memory_usage_bytes": memory_usage(client, config.HLL_KEY),
        "set_memory_usage_bytes": memory_usage(client, config.HLL_EXACT_SET_KEY),
    }
