"""趋势分类与异常标签测试（spec §5）。

标签只描述状态：这里刻意验证「没有 BUY / SELL 这种字眼混进输出」。
"""

from __future__ import annotations

import pytest

from src.rules import (
    ALERT_HIGH_VOLUME,
    ALERT_LARGE_MOVE,
    ALERT_NEW_20D_HIGH,
    ALERT_NEW_20D_LOW,
    ALERT_OVERBOUGHT,
    ALERT_OVERSOLD,
    TREND_DOWNTREND,
    TREND_INSUFFICIENT_DATA,
    TREND_NEUTRAL,
    TREND_STRONG_DOWNTREND,
    TREND_STRONG_UPTREND,
    TREND_UPTREND,
    alert_details,
    classify_trend,
    detect_alerts,
)

DEFAULT_THRESHOLDS = {
    "high_volume_ratio": 2.0,
    "large_move_pct": 4.0,
    "rsi_overbought": 70,
    "rsi_oversold": 30,
}


def metrics(**overrides):
    base = {
        "close": 100.0,
        "sma20": 95.0,
        "sma50": 90.0,
        "sma200": 80.0,
        "return_1d_pct": 0.5,
        "volume_ratio": 1.0,
        "rsi14": 50.0,
        "prev_20d_high": 105.0,
        "prev_20d_low": 80.0,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 趋势
# ---------------------------------------------------------------------------


def test_strong_uptrend():
    assert classify_trend(metrics(close=100.0, sma20=95.0, sma50=90.0, sma200=80.0)) == TREND_STRONG_UPTREND


def test_uptrend_when_sma200_above_sma50():
    assert classify_trend(metrics(close=100.0, sma20=95.0, sma50=90.0, sma200=92.0)) == TREND_UPTREND


def test_downtrend():
    assert classify_trend(metrics(close=80.0, sma20=85.0, sma50=90.0, sma200=70.0)) == TREND_DOWNTREND


def test_strong_downtrend():
    assert classify_trend(metrics(close=70.0, sma20=80.0, sma50=90.0, sma200=95.0)) == TREND_STRONG_DOWNTREND


def test_neutral_when_mixed():
    # Close 在 SMA20 上方但低于 SMA50 → 各种条件都不满足
    assert classify_trend(metrics(close=100.0, sma20=95.0, sma50=105.0, sma200=90.0)) == TREND_NEUTRAL


def test_insufficient_data_without_sma20_or_sma50():
    assert classify_trend(metrics(sma20=None)) == TREND_INSUFFICIENT_DATA
    assert classify_trend(metrics(sma50=None)) == TREND_INSUFFICIENT_DATA
    assert classify_trend(metrics(close=None)) == TREND_INSUFFICIENT_DATA


def test_missing_sma200_falls_back_to_plain_trend():
    assert classify_trend(metrics(close=100.0, sma20=95.0, sma50=90.0, sma200=None)) == TREND_UPTREND
    assert classify_trend(metrics(close=80.0, sma20=85.0, sma50=90.0, sma200=None)) == TREND_DOWNTREND


# ---------------------------------------------------------------------------
# 异常标签
# ---------------------------------------------------------------------------


def test_no_alerts_for_a_boring_day():
    assert detect_alerts(metrics(), DEFAULT_THRESHOLDS) == []


def test_large_move_boundary():
    assert ALERT_LARGE_MOVE in detect_alerts(metrics(return_1d_pct=-4.0), DEFAULT_THRESHOLDS)
    assert ALERT_LARGE_MOVE in detect_alerts(metrics(return_1d_pct=4.0), DEFAULT_THRESHOLDS)
    assert ALERT_LARGE_MOVE not in detect_alerts(metrics(return_1d_pct=3.99), DEFAULT_THRESHOLDS)
    assert ALERT_LARGE_MOVE not in detect_alerts(metrics(return_1d_pct=-3.99), DEFAULT_THRESHOLDS)


def test_high_volume_boundary():
    assert ALERT_HIGH_VOLUME in detect_alerts(metrics(volume_ratio=2.0), DEFAULT_THRESHOLDS)
    assert ALERT_HIGH_VOLUME not in detect_alerts(metrics(volume_ratio=1.99), DEFAULT_THRESHOLDS)


def test_rsi_boundaries():
    assert ALERT_OVERBOUGHT in detect_alerts(metrics(rsi14=70.0), DEFAULT_THRESHOLDS)
    assert ALERT_OVERBOUGHT not in detect_alerts(metrics(rsi14=69.9), DEFAULT_THRESHOLDS)
    assert ALERT_OVERSOLD in detect_alerts(metrics(rsi14=30.0), DEFAULT_THRESHOLDS)
    assert ALERT_OVERSOLD not in detect_alerts(metrics(rsi14=30.1), DEFAULT_THRESHOLDS)


def test_new_high_and_low_compare_against_previous_window():
    assert ALERT_NEW_20D_HIGH in detect_alerts(metrics(close=105.0, prev_20d_high=105.0), DEFAULT_THRESHOLDS)
    assert ALERT_NEW_20D_HIGH not in detect_alerts(metrics(close=104.9, prev_20d_high=105.0), DEFAULT_THRESHOLDS)
    assert ALERT_NEW_20D_LOW in detect_alerts(metrics(close=80.0, prev_20d_low=80.0), DEFAULT_THRESHOLDS)
    assert ALERT_NEW_20D_LOW not in detect_alerts(metrics(close=80.1, prev_20d_low=80.0), DEFAULT_THRESHOLDS)


def test_missing_metrics_do_not_produce_alerts():
    empty = {"close": None, "return_1d_pct": None, "volume_ratio": None, "rsi14": None, "prev_20d_high": None, "prev_20d_low": None}
    assert detect_alerts(empty, DEFAULT_THRESHOLDS) == []


def test_alert_order_is_stable_and_details_cite_evidence():
    alerts = detect_alerts(
        metrics(return_1d_pct=-5.0, volume_ratio=2.5, rsi14=28.0, close=70.0, prev_20d_low=75.0),
        DEFAULT_THRESHOLDS,
    )
    assert alerts == [ALERT_LARGE_MOVE, ALERT_HIGH_VOLUME, ALERT_NEW_20D_LOW, ALERT_OVERSOLD]

    details = alert_details(alerts, metrics(return_1d_pct=-5.0, volume_ratio=2.5, rsi14=28.0, close=70.0, prev_20d_low=75.0))
    assert len(details) == len(alerts)
    assert "-5.00%" in details[0]
    assert "2.50x" in details[1]
    assert "28" in details[3]
    # 标签不得输出买卖指令
    joined = " ".join(details).upper()
    for forbidden in ("BUY", "SELL", "买入", "卖出"):
        assert forbidden not in joined


def test_alert_details_handles_missing_value():
    details = alert_details([ALERT_OVERBOUGHT], {"rsi14": None})
    assert details == ["OVERBOUGHT (RSI14 n/a)"]
