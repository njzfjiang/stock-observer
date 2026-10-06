"""指标计算测试：口径 vs pandas/numpy 手算 + 数据不足时必须是 None 而不是 NaN。"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from src.indicators import (
    clean_number,
    drawdown_from_high,
    pct_change_over,
    previous_window_extremes,
    risk_metrics,
    rsi_last,
    rsi_wilder,
    simple_moving_average,
    summarize,
    volatility,
    volume_ratio,
)


def assert_no_nan(value, path: str = "metrics") -> None:
    """递归确认结果里没有 NaN / inf（spec §12「指标没有 NaN 灾难」）。"""
    if isinstance(value, dict):
        for key, item in value.items():
            assert_no_nan(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            assert_no_nan(item, f"{path}[{index}]")
    elif isinstance(value, float):
        assert not math.isnan(value), f"{path} is NaN"
        assert not math.isinf(value), f"{path} is inf"


# ---------------------------------------------------------------------------
# 基础函数
# ---------------------------------------------------------------------------


def test_clean_number_turns_nan_inf_into_none():
    assert clean_number(float("nan")) is None
    assert clean_number(float("inf")) is None
    assert clean_number(None) is None
    assert clean_number("abc") is None
    assert clean_number(True) is None
    assert clean_number(3) == 3.0


def test_simple_moving_average_matches_pandas(make_frame):
    closes = np.arange(1.0, 61.0)
    frame = make_frame(closes)
    assert simple_moving_average(frame["Close"], 20) == pytest.approx(closes[-20:].mean())
    assert simple_moving_average(frame["Close"], 50) == pytest.approx(closes[-50:].mean())
    assert simple_moving_average(frame["Close"], 200) is None  # 数据不足 → None


def test_pct_change_over_matches_manual(make_frame):
    closes = np.linspace(100.0, 150.0, 60)
    frame = make_frame(closes)
    expected = (closes[-1] / closes[-21] - 1) * 100
    assert pct_change_over(frame["Close"], 20) == pytest.approx(expected)
    assert pct_change_over(frame["Close"], 60) is None  # 只有 60 行，算 60D 需要 61 行


def test_rsi_extremes():
    rising = pd.Series(np.arange(1.0, 41.0))
    falling = pd.Series(np.arange(40.0, 0.0, -1.0))
    flat = pd.Series(np.full(40, 5.0))

    assert rsi_last(rising, 14) == pytest.approx(100.0)
    assert rsi_last(falling, 14) == pytest.approx(0.0)
    assert rsi_last(flat, 14) == pytest.approx(50.0)  # 完全不涨不跌 → 中性，而不是 NaN

    noisy = pd.Series(np.sin(np.arange(60) / 3.0) * 5 + 100)
    value = rsi_last(noisy, 14)
    assert 0.0 <= value <= 100.0


def test_rsi_needs_enough_history():
    assert rsi_last(pd.Series([1.0, 2.0, 3.0]), 14) is None
    assert rsi_wilder(pd.Series([1.0, 2.0, 3.0]), 14) is None


def test_volume_ratio_uses_previous_20_days_excluding_today():
    volumes = [100.0] * 20 + [250.0]  # 前 20 天都是 100，今天 250 → 2.5x
    assert volume_ratio(pd.Series(volumes), 20) == pytest.approx(2.5)

    volumes_with_spike = [100.0] * 20 + [1000.0]
    # 分子是今天，分母不含今天：即使今天爆量，量比也是 10 而不是 5
    assert volume_ratio(pd.Series(volumes_with_spike), 20) == pytest.approx(10.0)
    assert volume_ratio(pd.Series([100.0] * 5), 20) is None


def test_volatility_matches_numpy():
    returns = pd.Series(np.random.default_rng(7).normal(0, 0.02, 300))
    daily, annual = volatility(returns, 20, 252)
    expected = returns.iloc[-20:].std(ddof=1)
    assert daily == pytest.approx(expected * 100)
    assert annual == pytest.approx(expected * math.sqrt(252) * 100)
    assert volatility(pd.Series([0.01, 0.02]), 20, 252) == (None, None)


def test_drawdown_from_high():
    closes = [100.0, 120.0, 90.0]  # 高点 120，现价 90
    result = drawdown_from_high(pd.Series(closes), lookback=252)
    assert result["drawdown_from_high_pct"] == pytest.approx(-25.0)
    assert result["recent_high"] == pytest.approx(120.0)
    assert result["lookback_used"] == 3  # 自动收缩到可用行数

    one_point = drawdown_from_high(pd.Series([100.0]), lookback=252)
    assert one_point["drawdown_from_high_pct"] is None


def test_risk_metrics_uses_strict_window_and_matches_manual_calculation():
    prices = pd.Series(np.linspace(100.0, 150.0, 253))
    result = risk_metrics(prices, window=252, annual_risk_free_rate=0.04)

    returns = prices.pct_change(fill_method=None).iloc[-252:]
    daily_rf = (1.04 ** (1 / 252)) - 1
    expected_sharpe = (returns - daily_rf).mean() / (returns - daily_rf).std(ddof=1) * math.sqrt(252)
    assert result["risk_status"] == "OK"
    assert result["current_drawdown_252d_pct"] == pytest.approx(0.0)
    assert result["max_drawdown_252d_pct"] == pytest.approx(0.0)
    assert result["sharpe_252d"] == pytest.approx(expected_sharpe)
    assert result["risk_free_rate_annual_pct"] == pytest.approx(4.0)


def test_risk_metrics_does_not_shorten_window_and_zero_volatility_is_null():
    short = risk_metrics(pd.Series(np.linspace(100.0, 120.0, 252)), window=252, annual_risk_free_rate=0.04)
    assert short["risk_status"] == "DATA_INSUFFICIENT"
    assert short["current_drawdown_252d_pct"] is None
    assert short["max_drawdown_252d_pct"] is None
    assert short["sharpe_252d"] is None

    flat = risk_metrics(pd.Series(np.full(253, 100.0)), window=252, annual_risk_free_rate=0.04)
    assert flat["risk_status"] == "OK"
    assert flat["current_drawdown_252d_pct"] == pytest.approx(0.0)
    assert flat["max_drawdown_252d_pct"] == pytest.approx(0.0)
    assert flat["sharpe_252d"] is None


def test_risk_metrics_max_drawdown_uses_running_peak():
    prices = np.full(253, 100.0)
    prices[-3:] = [120.0, 90.0, 96.0]
    result = risk_metrics(pd.Series(prices), window=252, annual_risk_free_rate=0.0)

    assert result["risk_status"] == "OK"
    assert result["current_drawdown_252d_pct"] == pytest.approx(-20.0)
    assert result["max_drawdown_252d_pct"] == pytest.approx(-25.0)


def test_previous_window_extremes_excludes_today():
    closes = [100.0] * 20 + [999.0]  # 今天创新高，但「前 20 日」极值不含今天
    high, low = previous_window_extremes(pd.Series(closes), 20)
    assert high == pytest.approx(100.0)
    assert low == pytest.approx(100.0)

    ascending = np.arange(1.0, 30.0)
    high, low = previous_window_extremes(pd.Series(ascending), 20)
    assert high == pytest.approx(ascending[-2])
    assert low == pytest.approx(ascending[-21])


# ---------------------------------------------------------------------------
# summarize（一只股票的完整指标）
# ---------------------------------------------------------------------------


def test_summarize_full_history(make_frame, settings):
    closes = np.linspace(100.0, 200.0, 260)
    frame = make_frame(closes)
    metrics = summarize(frame, settings)

    assert metrics["history_rows"] == 260
    assert metrics["close"] == pytest.approx(200.0)
    assert metrics["sma20"] == pytest.approx(round(closes[-20:].mean(), 6), abs=1e-6)
    assert metrics["sma50"] is not None
    assert metrics["sma200"] is not None
    assert metrics["sma200_available"] is True
    assert metrics["return_1d_pct"] == pytest.approx(round((closes[-1] / closes[-2] - 1) * 100, 6), abs=1e-6)
    assert metrics["return_60d_pct"] == pytest.approx(round((closes[-1] / closes[-61] - 1) * 100, 6), abs=1e-6)
    assert metrics["returns_basis"] == "adj_close"
    assert metrics["volume_ratio"] == pytest.approx(1.0)  # 成交量恒定
    assert metrics["drawdown_from_high_pct"] == pytest.approx(0.0)  # 一路上涨，正在高点
    assert metrics["date"] == frame.index[-1].strftime("%Y-%m-%d")
    assert_no_nan(metrics)


def test_summarize_short_history_has_no_nan_disaster(make_frame, settings):
    """只有 40 个交易日：SMA50/200 之类的指标必须变成 None，不许是 NaN。"""
    closes = np.linspace(50.0, 60.0, 40)
    frame = make_frame(closes)
    metrics = summarize(frame, settings)

    assert metrics["sma20"] is not None
    assert metrics["sma50"] is None
    assert metrics["sma200"] is None
    assert metrics["sma200_available"] is False
    assert metrics["return_60d_pct"] is None
    assert any("200" in note for note in metrics["notes"])
    assert_no_nan(metrics)


def test_summarize_without_adj_close_falls_back_to_close(make_frame, settings):
    closes = np.linspace(10.0, 20.0, 260)
    frame = make_frame(closes, with_adj_close=False)
    metrics = summarize(frame, settings)

    assert metrics["returns_basis"] == "close"
    assert metrics["close"] == pytest.approx(20.0)
    assert any("复权" in note for note in metrics["notes"])
    assert_no_nan(metrics)


def test_returns_use_adjusted_close(make_frame, settings):
    """除权缺口：Close 掉一半，但复权价连续 —— 收益率必须用复权价算。"""
    closes = np.concatenate([np.full(239, 100.0), np.full(21, 50.0)])
    adjusted = np.full(260, 100.0)
    frame = make_frame(closes, adj_close=adjusted)
    metrics = summarize(frame, settings)

    assert metrics["close"] == pytest.approx(50.0)              # 展示原始价
    assert metrics["adjusted_close"] == pytest.approx(100.0)
    assert metrics["return_20d_pct"] == pytest.approx(0.0)      # 复权后没有涨跌
    assert metrics["returns_basis"] == "adj_close"
    assert metrics["current_drawdown_252d_pct"] == pytest.approx(0.0)  # 风险回撤同样必须使用复权价
    assert metrics["max_drawdown_252d_pct"] == pytest.approx(0.0)
