"""Redis connection helpers."""

from __future__ import annotations

import logging

import redis

log = logging.getLogger("analytics.redis")


class RedisUnavailable(RuntimeError):
    """Redis could not be reached; the message says how to fix it."""


def connect(url: str) -> redis.Redis:
    """Connect to ``url`` and verify the connection with PING."""
    client = redis.Redis.from_url(url, socket_connect_timeout=5, decode_responses=False)
    try:
        if not client.ping():
            raise RedisUnavailable(f"Redis at {_redacted(url)} did not answer PING")
    except redis.exceptions.RedisError as exc:
        raise RedisUnavailable(
            f"Cannot connect to Redis at {_redacted(url)}: {exc}. "
            "Start one with `docker run --name my-redis -p 6379:6379 -d redis` "
            "or set REDIS_URL."
        ) from exc
    log.info("PING -> PONG (%s)", _redacted(url))
    return client


def _redacted(url: str) -> str:
    """Hide any password in a redis URL before it is logged."""
    if "@" not in url:
        return url
    scheme, rest = url.split("://", 1) if "://" in url else ("redis", url)
    return f"{scheme}://***@{rest.rsplit('@', 1)[1]}"


def memory_usage(client: redis.Redis, key: str) -> int:
    """Return MEMORY USAGE for ``key`` in bytes; raise if the key does not exist."""
    size = client.memory_usage(key)
    log.info("MEMORY USAGE %s -> %s bytes", key, size)
    if size is None:
        raise KeyError(f"MEMORY USAGE: key {key!r} does not exist")
    return int(size)
