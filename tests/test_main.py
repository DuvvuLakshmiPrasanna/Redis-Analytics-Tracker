"""End-to-end: run main() and validate the files against the specification's schemas."""

import json

import pytest

import main
from src.analytics import config
from tests.conftest import SMALL, TEST_URL

HLL_SCHEMA = {"day": str, "true_unique_count": int, "hll_unique_count": int,
              "error_rate_percentage": float, "hll_memory_usage_bytes": int, "set_memory_usage_bytes": int}
BITMAP_SCHEMA = {"dau_date": str, "dau_count": int, "wau_period": str, "wau_count": int,
                 "bitmap_memory_per_day_bytes": int, "set_memory_for_dau_bytes": int}


def check(data: dict, schema: dict) -> None:
    assert set(data) == set(schema), "exactly the specified keys, no extras"
    for key, kind in schema.items():
        assert type(data[key]) is kind, f"{key}: {type(data[key]).__name__} is not {kind.__name__}"


def test_single_command_produces_both_valid_reports(redis_client, tmp_path, monkeypatch):
    monkeypatch.setenv("REDIS_URL", TEST_URL)
    out = tmp_path / "nested" / "results"  # does not exist: main must create it
    assert main.main([*SMALL, "--results-dir", str(out)]) == 0

    hll = json.loads((out / "hll_analysis.json").read_text())
    bitmap = json.loads((out / "bitmap_analysis.json").read_text())
    check(hll, HLL_SCHEMA)
    check(bitmap, BITMAP_SCHEMA)
    for key in ("hll_memory_usage_bytes", "set_memory_usage_bytes"):
        assert hll[key] > 0
    for key in ("bitmap_memory_per_day_bytes", "set_memory_for_dau_bytes"):
        assert bitmap[key] > 0
    assert hll["error_rate_percentage"] == pytest.approx(
        (hll["hll_unique_count"] - hll["true_unique_count"]) / hll["true_unique_count"] * 100)
    assert hll["day"] == "2024-10-26"
    assert redis_client.exists(config.HLL_KEY) and redis_client.exists(config.WAU_KEY)
    assert all(redis_client.exists(k) for k in config.DAU_KEYS)
    assert not list(out.glob(".*.tmp")), "no temp files left behind"
    for name in ("hll_analysis.json", "bitmap_analysis.json"):
        mode = (out / name).stat().st_mode & 0o777
        assert mode & 0o044 == 0o044, f"{name} must be world-readable (got {oct(mode)})"


def test_unreachable_redis_gives_clean_exit_code(tmp_path, monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    assert main.main([*SMALL, "--results-dir", str(tmp_path)]) == 2
    assert not list(tmp_path.iterdir())


def test_password_in_redis_url_never_appears_in_logs(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("REDIS_URL", "redis://user:SuperSecret123@127.0.0.1:1/0")
    with caplog.at_level("DEBUG"):
        assert main.main([*SMALL, "--results-dir", str(tmp_path)]) == 2
    assert "SuperSecret123" not in caplog.text
    assert "127.0.0.1:1" in caplog.text  # still tells you where it tried


def test_invalid_parameters_exit_code(tmp_path):
    assert main.main(["--events", "5", "--unique", "10", "--results-dir", str(tmp_path)]) == 2


def test_env_example_documents_redis_url():
    text = (config.PROJECT_ROOT / ".env.example").read_text()
    assert "REDIS_URL=redis://localhost:6379" in text.splitlines()
    assert not (config.PROJECT_ROOT / ".env").exists()
