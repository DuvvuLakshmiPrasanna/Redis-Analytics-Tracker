# Redis Analytics Tracker: HyperLogLog and Bitmaps

A script-based analytics engine that simulates high-volume e-commerce traffic and uses **Redis HyperLogLog** (approximate unique visitors) and **Redis Bitmaps** (exact daily/weekly active users and cohort maths with `BITOP`) to answer "how many unique users?" in a few kilobytes instead of tens of megabytes. For each technique it also builds the naive exact alternative (a Redis Set), measures both with `MEMORY USAGE`, and writes the accuracy and memory trade-off to `results/hll_analysis.json` and `results/bitmap_analysis.json`. **One command runs everything:** `python main.py`.

**Headline results** (full-scale run, Redis 7.0.15, 1,000,000 events / 500,000 unique visitors, 7 days × 300,000 active users):

| | Probabilistic / bitmap | Exact Set | Saving |
|---|---|---|---|
| Unique visitors | HyperLogLog: **14,408 B**, estimate 506,483 vs true 500,000 (**+1.30%**) | 24,194,448 B | **1,679× smaller** |
| Daily active users | Bitmap: **163,896 B**, count exact (300,000) | 15,891,584 B | **97× smaller** |

## Quick start

You need Python 3.10+ and a Redis server (Docker is the easiest way to get one).

```bash
# 1. Start Redis (skip if you already have one)
docker run --name my-redis -p 6379:6379 -d redis

# 2. Install and configure
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # contains REDIS_URL=redis://localhost:6379

# 3. Run the entire analysis (takes about 20 seconds)
python main.py
```

The two reports appear in `results/`. If `REDIS_URL` is unset the script defaults to `redis://localhost:6379`; to use a cloud Redis (Redis Cloud, Upstash) put its URL in `.env`.

**Or with Docker only** (Redis + the analysis in one command, reports land in `./results`):

```bash
docker compose up --build --abort-on-container-exit
```

> The Docker Compose path was written and its YAML parsed, but I could not run it: the machine I built this on had no Docker daemon. Everything else in this README was executed against a real Redis server. If Compose misbehaves, the Quick start above is the verified path.

Optional: `python main.py --help` lists scale knobs (`--events`, `--unique`, `--dau`, `--core`, `--id-space`, `--seed`, `--results-dir`). The defaults match the specification.

## What it does

```
Data simulator ──► Redis client ──► Redis ──► Analysis & reporting ──► results/*.json
 (seeded RNG)     PFADD / SADD      PFCOUNT / BITCOUNT /           error rate, memory,
                  SETBIT / BITOP    MEMORY USAGE / SCARD           atomic JSON write
```

**Part 1: HyperLogLog** (`src/analytics/hll.py`). 1,000,000 visitor events containing exactly 500,000 distinct ids (the rest are repeat visits, shuffled in) are sent in batches of 10,000 to `PFADD visitors:daily:2024-10-26` and, at the same time, to `SADD visitors:daily:2024-10-26:exact`. The true count is a local Python `set`; the Redis `SCARD` must agree with it or the run aborts. `PFCOUNT` gives the estimate, `MEMORY USAGE` sizes both keys, and `error_rate_percentage = ((hll - true) / true) * 100`.

**Part 2: Bitmaps** (`src/analytics/bitmap.py`). For 7 consecutive days (`2024-10-20` to `2024-10-26`) integer user ids become bit offsets via `SETBIT dau:<day> <id> 1`. `BITOP OR wau:2024-w43 dau:…` (all 7 keys) builds the weekly bitmap, `BITCOUNT` counts DAU and WAU, and the same day's users are stored in a Set to compare memory. A fixed core of 100,000 users is active every day and the rest are sampled randomly, so days overlap. Bitmap counts are exact, so they are checked against the script's own ground truth and the run aborts on any mismatch.

### Output files

`results/hll_analysis.json`, from the real run:

```json
{
  "day": "2024-10-26",
  "true_unique_count": 500000,
  "hll_unique_count": 506483,
  "error_rate_percentage": 1.2966,
  "hll_memory_usage_bytes": 14408,
  "set_memory_usage_bytes": 24194448
}
```

`results/bitmap_analysis.json`:

```json
{
  "dau_date": "2024-10-26",
  "dau_count": 300000,
  "wau_period": "2024-w43",
  "wau_count": 845536,
  "bitmap_memory_per_day_bytes": 163896,
  "set_memory_for_dau_bytes": 15891584
}
```

Both contain exactly the specified keys and types (the error rate is always a float, memory values are positive integers). `results/` is created if missing, files are written atomically and are world-readable. The keys stay in Redis after the run so you can inspect them:

```bash
redis-cli pfcount visitors:daily:2024-10-26   # 506483
redis-cli bitcount wau:2024-w43               # 845536
redis-cli memory usage dau:2024-10-26         # 163896
```

## Results and trade-offs

### HyperLogLog: ~1,700× less memory for ~1% error

HLL used 14,408 bytes (a 12 KB register array plus Redis overhead) versus 24 MB for the Set, and that size is **fixed**: counting 5 billion visitors would still cost about 12 KB, while the Set grows by roughly 48 bytes per visitor. The price is accuracy: this run was off by **+1.30%**.

**Is 1.30% a problem?** The documented 0.81% is a *standard error* (one sigma), so a single run landing 1.6σ away is ordinary. I did not want to assume that, so `scripts/error_distribution.py` measures 40 independent sets of 500,000 ids:

| Check | Measured | Theory |
|---|---|---|
| RMS error | **0.77%** | 0.81% |
| Mean error (bias) | +0.19% | ~0 |
| Within 1σ (≤ 0.81%) | 25/40 = 62% | ~68% |
| Within 2σ (≤ 1.62%) | 39/40 | ~95% |
| Worst trial | 1.68% | |

So HLL behaves as documented, and the +1.30% run is a normal draw, not a bug. Two consequences: expect to be a percent or two off on any single count, and you **cannot** subtract two HLL counts to get a precise small difference (the error on each is far larger than the difference). **Reproducibility note:** the project's FAQ says results differ between runs, but this script is seeded and its ids are the same strings every time, so `main.py` produces the *same* HLL estimate on every run. Use `--seed` or `scripts/error_distribution.py` (fresh ids each trial) to see the variation.

### Bitmaps: exact, and a 97× saving, *when ids are dense*

Bitmaps give exact counts, support set algebra with `BITOP`, and here cost 163,896 bytes versus 15.9 MB for a Set of the same 300,000 users. The weekly union (`BITOP OR`) found **845,536** distinct users across the week from 300,000 per day.

The saving depends entirely on **id density**, because a bitmap's size is set by the *highest user id*, not by how many users there are (the 2024-10-26 key is 125,001 bytes because the largest id is about 1,000,000). I measured where it stops paying off, with ids drawn from 1–1,000,000:

| Active users | Density | Bitmap | Set | Smaller |
|---|---|---|---|---|
| 500 | 0.05% | 163,888 B | 2,096 B | **Set** |
| 2,000 | 0.20% | 131,120 B | 80,488 B | **Set** |
| 5,000 | 0.50% | 196,656 B | 258,408 B | Bitmap |
| 20,000 | 2.00% | 131,120 B | 1,033,320 B | Bitmap |
| 300,000 | 30.00% | 163,888 B | 15,891,560 B | Bitmap |

The crossover sits between 0.2% and 0.5% density. Below it a Set is cheaper (and a UUID-keyed system needs an id→integer mapping first, as the FAQ notes). Bitmap sizes in this table vary a little (131 KB to 197 KB for similar maximum ids) because `MEMORY USAGE` includes allocator over-allocation as Redis grows the string; treat them as approximate.

### When to use which

| Question | Use | Why |
|---|---|---|
| "About how many unique visitors today?" at any scale | **HyperLogLog** | fixed ~12 KB, ~0.8% standard error, mergeable with `PFCOUNT a b` |
| "Was user 123 active?", exact DAU/WAU, retention, cohorts | **Bitmap** | exact, O(1) per user, `BITOP AND/OR/XOR` for cohorts |
| Few active users out of a huge id range | **Set** | a bitmap would be mostly zeros |
| You need the actual member list | **Set** | neither HLL nor a bitmap can enumerate cheaply |

## Design notes

- **Fixed names from the spec:** HLL key `visitors:daily:2024-10-26`; bitmaps `dau:2024-10-20` … `dau:2024-10-26`; weekly key `wau:2024-w43`.
- **The `2024-w43` label is used verbatim.** 20–26 Oct 2024 is Sunday to Saturday; ISO week 43 is actually 21–27 Oct. The label is a fixed identifier here, not a computed ISO week.
- **Safe to re-run:** each part deletes only its own keys first, so repeated runs never accumulate into an old HLL.
- **Throughput:** commands are pipelined in batches (no transaction), which is why over 4 million element-level Redis operations finish in about 20 seconds.
- **Failure handling:** an unreachable Redis exits with code 2 and a message explaining how to start one (any password in the URL is masked in logs); invalid parameters also exit 2; a failed run leaves no partial or temp files in `results/`.
- **Code layout:** the simulator, Redis operations, and reporting are separate modules with no hidden global state, mirroring the architecture in the brief.

```
main.py                    single entry point
src/analytics/config.py    fixed keys/dates + workload size + REDIS_URL
src/analytics/simulator.py seeded event and daily-active-user generation
src/analytics/hll.py       Part 1 (PFADD / PFCOUNT / SADD / MEMORY USAGE)
src/analytics/bitmap.py    Part 2 (SETBIT / BITOP OR / BITCOUNT / MEMORY USAGE)
src/analytics/redis_client.py  connection + MEMORY USAGE helper
src/analytics/reporting.py atomic JSON writer
scripts/error_distribution.py  the 40-trial HLL accuracy check above
tests/                     20 tests (real Redis; skip cleanly if none)
.env.example               REDIS_URL=redis://localhost:6379
```

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q          # 20 tests, <1 s
```

The integration tests talk to a **real Redis** (default `redis://localhost:6379/15`, override with `TEST_REDIS_URL`) and write reports to a temporary directory, so they never overwrite your `results/`. They delete only this project's keys, never `FLUSHDB`. They cover: exact unique counts and overlap in the simulator; the error formula; HLL/bitmap key existence and types; DAU/WAU exactness against ground truth; `BITOP OR` against a hand-computed union and an `AND` cohort; re-run idempotence; the exact JSON schemas and types; file permissions; and the unreachable-Redis exit path. I also checked the tests can fail: swapping `OR` for `AND`, or using the wrong denominator in the error formula, each makes 3 tests fail.

## Requirements checklist

| Requirement | Where |
|---|---|
| README with single-command run | this file; `python main.py` |
| `.env.example` with `REDIS_URL` | `.env.example` |
| `PFADD` into `visitors:daily:2024-10-26` | `src/analytics/hll.py` |
| `results/hll_analysis.json`, exact schema | `main.py`, `tests/test_main.py` |
| `SETBIT` for 7 days → 7 keys | `src/analytics/bitmap.py` |
| `BITOP OR` into `wau:2024-w43` | `src/analytics/bitmap.py` |
| `results/bitmap_analysis.json`, exact schema | `main.py`, `tests/test_main.py` |
| `MEMORY USAGE` for all four sizes (positive ints) | `src/analytics/redis_client.py::memory_usage` |
| Error rate formula (float) | `src/analytics/hll.py::error_rate_percentage` |
| `results/` created if missing | `src/analytics/reporting.py` |

## Limitations

- Numbers come from **one machine and Redis 7.0.15**. `MEMORY USAGE` depends on Redis version, encoding and allocator, so your byte counts will differ somewhat; the *ratios* (≈1,000×+ for HLL, ≈100× for dense bitmaps) are the point.
- The data is synthetic and uniform. Real visitor traffic is skewed, which does not affect HLL accuracy but does affect how dense your id space is.
- Part 2 uses small contiguous integer ids by design. Mapping real UUIDs to offsets is out of scope (the brief allows this).
