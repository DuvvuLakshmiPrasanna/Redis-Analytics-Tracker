"""Shared fixtures. Tests that need Redis use the server at TEST_REDIS_URL (default db 15)
and skip cleanly when none is reachable."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analytics import config  # noqa: E402
from src.analytics.redis_client import RedisUnavailable, connect  # noqa: E402

TEST_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15")

SMALL = ["--events", "6000", "--unique", "3000", "--dau", "900", "--core", "300", "--id-space", "5000"]


@pytest.fixture()
def redis_client():
    try:
        client = connect(TEST_URL)
    except RedisUnavailable as exc:
        pytest.skip(f"no Redis reachable at {TEST_URL}: {exc}")
    client.delete(*config.ALL_KEYS)
    yield client
    client.delete(*config.ALL_KEYS)  # only this project's keys, never FLUSHDB
