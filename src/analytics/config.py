"""Hard-coded analysis parameters and environment configuration.

The days, key names and period label are fixed by the project specification, so
they are constants here rather than options.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = PROJECT_ROOT / "results"

DEFAULT_REDIS_URL = "redis://localhost:6379"

# --- Part 1: HyperLogLog -------------------------------------------------------
HLL_DAY = "2024-10-26"
HLL_KEY = f"visitors:daily:{HLL_DAY}"
HLL_EXACT_SET_KEY = f"{HLL_KEY}:exact"

# --- Part 2: Bitmaps -----------------------------------------------------------
# Seven consecutive days ending on the HLL day.
LAST_DAY = date(2024, 10, 26)
DAYS: tuple[str, ...] = tuple(
    (LAST_DAY - timedelta(days=offset)).isoformat() for offset in range(6, -1, -1)
)
DAU_KEYS: tuple[str, ...] = tuple(f"dau:{d}" for d in DAYS)
DAU_DATE = DAYS[-1]
DAU_KEY = f"dau:{DAU_DATE}"
DAU_EXACT_SET_KEY = f"{DAU_KEY}:exact"

# The specification names this period "2024-w43" even though 20-26 Oct 2024 is
# Sunday-to-Saturday and ISO week 43 is 21-27 Oct. The label is kept verbatim.
WAU_PERIOD = "2024-w43"
WAU_KEY = f"wau:{WAU_PERIOD}"

ALL_KEYS: tuple[str, ...] = (
    HLL_KEY,
    HLL_EXACT_SET_KEY,
    *DAU_KEYS,
    DAU_EXACT_SET_KEY,
    WAU_KEY,
)


@dataclass(frozen=True)
class SimulationParams:
    """Size of the simulated workload. Defaults match the specification."""

    total_events: int = 1_000_000
    unique_visitors: int = 500_000
    user_id_space: int = 1_000_000  # bitmap offsets are drawn from 1..user_id_space
    daily_active_users: int = 300_000
    core_users: int = 100_000  # active every day, guarantees cross-day overlap
    seed: int = 42
    batch_size: int = 10_000

    def validate(self) -> None:
        if self.unique_visitors < 1 or self.total_events < self.unique_visitors:
            raise ValueError("total_events must be >= unique_visitors >= 1")
        if not 0 <= self.core_users <= self.daily_active_users <= self.user_id_space:
            raise ValueError("need 0 <= core_users <= daily_active_users <= user_id_space")
        if self.batch_size < 1:
            raise ValueError("batch_size must be >= 1")


def redis_url() -> str:
    """Read REDIS_URL from the environment (a .env file is loaded by main.py)."""
    return os.environ.get("REDIS_URL", "").strip() or DEFAULT_REDIS_URL
