"""Measure HyperLogLog error over many *different* id sets.

A single run of main.py always uses the same ids, so its HLL estimate is the same every time.
To check the documented ~0.81% standard error you need many independent id sets:

    python -m scripts.error_distribution --trials 40 --unique 500000
"""

from __future__ import annotations

import argparse
import math
import statistics
import sys
import uuid

from dotenv import load_dotenv

from src.analytics import config
from src.analytics.redis_client import RedisUnavailable, connect

KEY = "scratch:hll:error-distribution"  # scratch key, deleted after every trial


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--trials", type=int, default=40)
    p.add_argument("--unique", type=int, default=500_000)
    p.add_argument("--batch", type=int, default=50_000)
    args = p.parse_args(argv)
    load_dotenv()
    try:
        client = connect(config.redis_url())
    except RedisUnavailable as exc:
        print(exc, file=sys.stderr)
        return 2

    errors: list[float] = []
    for _ in range(args.trials):
        salt = uuid.uuid4().hex  # a fresh, independent set of ids each trial
        client.delete(KEY)
        for start in range(0, args.unique, args.batch):
            stop = min(start + args.batch, args.unique)
            client.pfadd(KEY, *(f"{salt}:{i}" for i in range(start, stop)))
        errors.append((client.pfcount(KEY) - args.unique) / args.unique * 100)
        client.delete(KEY)

    rms = math.sqrt(statistics.fmean(e * e for e in errors))
    within = sum(abs(e) <= 0.81 for e in errors)
    print(f"trials={args.trials} unique={args.unique:,}")
    print(f"mean error   = {statistics.fmean(errors):+.4f}%   (bias; should be near 0)")
    print(f"RMS error    = {rms:.4f}%   (documented standard error: 0.81%)")
    print(f"max |error|  = {max(abs(e) for e in errors):.4f}%")
    print(f"within 1 sigma (<=0.81%): {within}/{args.trials} = {within / args.trials:.0%}  (theory: ~68%)")
    print(f"within 2 sigma (<=1.62%): {sum(abs(e) <= 1.62 for e in errors)}/{args.trials}  (theory: ~95%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
