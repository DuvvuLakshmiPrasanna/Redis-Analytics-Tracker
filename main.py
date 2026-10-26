"""Run the full analysis with one command:  python main.py

1. Part 1: HyperLogLog vs Set for unique visitors  -> results/hll_analysis.json
2. Part 2: Bitmaps for DAU / WAU                   -> results/bitmap_analysis.json
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import replace
from pathlib import Path

from dotenv import load_dotenv

from src.analytics import config
from src.analytics.bitmap import run_bitmap_analysis
from src.analytics.hll import run_hll_analysis
from src.analytics.redis_client import RedisUnavailable, connect
from src.analytics.reporting import write_json
from src.analytics.simulator import generate_daily_active_users, generate_visitor_events

log = logging.getLogger("analytics")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    d = config.SimulationParams()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--events", type=int, default=d.total_events, help="visitor events to simulate")
    p.add_argument("--unique", type=int, default=d.unique_visitors, help="distinct visitors among them")
    p.add_argument("--dau", type=int, default=d.daily_active_users, help="active users per day")
    p.add_argument("--core", type=int, default=d.core_users, help="users active on all 7 days")
    p.add_argument("--id-space", type=int, default=d.user_id_space, help="largest integer user id")
    p.add_argument("--seed", type=int, default=d.seed, help="random seed (runs are reproducible)")
    p.add_argument("--results-dir", type=Path, default=config.RESULTS_DIR, help="where the JSON reports go")
    return p.parse_args(argv)


def build_params(args: argparse.Namespace) -> config.SimulationParams:
    params = replace(
        config.SimulationParams(),
        total_events=args.events,
        unique_visitors=args.unique,
        daily_active_users=args.dau,
        core_users=args.core,
        user_id_space=args.id_space,
        seed=args.seed,
    )
    params.validate()
    return params


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_dotenv()  # reads .env if present; real environment variables win
    try:
        args = parse_args(argv)
        params = build_params(args)
    except ValueError as exc:
        log.error("invalid parameters: %s", exc)
        return 2

    try:
        client = connect(config.redis_url())
    except RedisUnavailable as exc:
        log.error("%s", exc)
        return 2

    started = time.perf_counter()
    log.info("Part 1: HyperLogLog (%d events, %d unique)", params.total_events, params.unique_visitors)
    hll_report = run_hll_analysis(client, generate_visitor_events(params), params)
    hll_path = write_json(args.results_dir, "hll_analysis.json", hll_report)

    log.info("Part 2: Bitmaps (%d days, %d active users/day)", len(config.DAYS), params.daily_active_users)
    daily = generate_daily_active_users(params, config.DAYS)
    bitmap_report = run_bitmap_analysis(client, daily, params)
    bitmap_path = write_json(args.results_dir, "bitmap_analysis.json", bitmap_report)

    log.info("done in %.1fs -> %s, %s", time.perf_counter() - started, hll_path, bitmap_path)
    print_summary(hll_report, bitmap_report)
    return 0


def print_summary(hll: dict, bitmap: dict) -> None:
    h_ratio = hll["set_memory_usage_bytes"] / hll["hll_memory_usage_bytes"]
    b_ratio = bitmap["set_memory_for_dau_bytes"] / bitmap["bitmap_memory_per_day_bytes"]
    print("\n=== Summary ===")
    print(f"HLL    : true={hll['true_unique_count']:,} estimate={hll['hll_unique_count']:,} "
          f"error={hll['error_rate_percentage']:+.4f}%")
    print(f"         memory HLL={hll['hll_memory_usage_bytes']:,} B vs Set={hll['set_memory_usage_bytes']:,} B "
          f"({h_ratio:,.0f}x smaller)")
    print(f"Bitmap : DAU({bitmap['dau_date']})={bitmap['dau_count']:,} "
          f"WAU({bitmap['wau_period']})={bitmap['wau_count']:,}")
    print(f"         memory bitmap={bitmap['bitmap_memory_per_day_bytes']:,} B vs Set="
          f"{bitmap['set_memory_for_dau_bytes']:,} B ({b_ratio:,.1f}x smaller)")


if __name__ == "__main__":
    sys.exit(main())
