"""配置与关注列表测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config import ConfigError, load_config, load_watchlist, parse_watchlist

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"


def test_parse_watchlist_handles_comments_blanks_and_duplicates():
    lines = [
        "# 这是注释\n",
        "\n",
        "aapl  # 苹果\n",
        "MSFT\n",
        " aapl \n",
        "TSLA\n",
        "not a ticker\n",
        "BRK.B\n",
        "$$$bad$$$\n",
    ]
    tickers, rejected = parse_watchlist(lines)

    assert tickers == ["AAPL", "MSFT", "TSLA", "BRK.B"]
    assert [lineno for lineno, _ in rejected] == [7, 9]


def test_parse_watchlist_rejects_overlong_tokens():
    tickers, rejected = parse_watchlist(["ABCDEFGHIJKLM\n"])
    assert tickers == []
    assert len(rejected) == 1


def test_load_config_reads_project_config():
    settings = load_config(CONFIG_PATH)

    assert settings.project_root == CONFIG_PATH.parent
    assert settings.get("project", "benchmark") == "QQQ"
    assert settings.get("project", "market_tickers") == ["SPY", "QQQ"]
    assert settings.section("thresholds")["large_move_pct"] == 4.0
    assert settings.section("attention_score")["trend"]["weight"] == 30
    assert settings.section("risk") == {"window": 252, "annual_risk_free_rate": 0.04}
    assert settings.outputs_dir.name == "outputs"
    assert settings.output_path("daily_report").name == "daily_report.md"


def test_config_overrides_do_not_touch_original(settings):
    overridden = settings.with_overrides(period="3y", output_dir="tmp-out")
    assert overridden.get("history", "period") == "3y"
    assert settings.get("history", "period") == "2y"
    assert settings.get("outputs", "dir") == "outputs"


def test_load_config_missing_file(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.yaml")


def test_load_watchlist_project_file():
    tickers = load_watchlist(CONFIG_PATH.parent / "watchlist.txt")
    assert "NVDA" in tickers
    assert "QQQ" in tickers and "SPY" in tickers
    assert len(tickers) == len(set(tickers))


def test_load_watchlist_missing_file(tmp_path):
    with pytest.raises(ConfigError):
        load_watchlist(tmp_path / "nope.txt")
