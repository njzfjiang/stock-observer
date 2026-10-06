"""Attention Score 测试（spec §6）：总分必须等于各分项之和，权重来自 config。"""

from __future__ import annotations

import pytest

from src.scoring import attention_score

SCORE_CFG = {
    "enabled": True,
    "trend": {
        "weight": 30,
        "scores": {
            "STRONG_UPTREND": 1.0,
            "UPTREND": 0.55,
            "NEUTRAL": 0.0,
            "DOWNTREND": 0.55,
            "STRONG_DOWNTREND": 1.0,
            "INSUFFICIENT_DATA": 0.0,
        },
    },
    "momentum_20d": {"weight": 20, "full_credit_abs_return_pct": 15.0},
    "relative_strength": {"weight": 20, "full_credit_abs_diff_pct": 10.0},
    "volume_activity": {"weight": 15, "baseline_ratio": 1.0, "full_credit_ratio": 2.5},
    "price_event": {
        "weight": 15,
        "per_alert_credit": 0.5,
        "alerts": ["LARGE_MOVE", "NEW_20D_HIGH", "NEW_20D_LOW", "OVERBOUGHT", "OVERSOLD"],
    },
}

RS_KEY = "relative_strength_20d_vs_qqq"


def metrics(**overrides):
    base = {
        "trend": "NEUTRAL",
        "return_20d_pct": 0.0,
        "volume_ratio": 1.0,
        RS_KEY: 0.0,
    }
    base.update(overrides)
    return base


def score_of(m, alerts=()):
    return attention_score(m, list(alerts), SCORE_CFG, relative_strength_window=20, benchmark="QQQ", decimals=1)


def test_total_equals_sum_of_components():
    result = score_of(metrics(trend="STRONG_UPTREND", return_20d_pct=7.5, volume_ratio=1.8, **{RS_KEY: -3.0}), ["LARGE_MOVE"])
    assert result["score"] == pytest.approx(round(sum(c["points"] for c in result["components"]), 1))
    assert [c["key"] for c in result["components"]] == [
        "trend",
        "momentum_20d",
        "relative_strength",
        "volume_activity",
        "price_event",
    ]
    assert result["max_score"] == pytest.approx(100.0)


def test_strong_trend_and_everything_maxed_is_100():
    result = score_of(
        metrics(trend="STRONG_DOWNTREND", return_20d_pct=-15.0, volume_ratio=3.0, **{RS_KEY: -12.0}),
        ["LARGE_MOVE", "NEW_20D_LOW", "OVERSOLD"],
    )
    assert result["score"] == pytest.approx(100.0)
    assert all(c["points"] == c["max_points"] for c in result["components"])


def test_boring_day_scores_zero():
    result = score_of(metrics())
    assert result["score"] == pytest.approx(0.0)


def test_direction_does_not_matter_for_trend_component():
    up = score_of(metrics(trend="STRONG_UPTREND"))
    down = score_of(metrics(trend="STRONG_DOWNTREND"))
    assert up["score"] == pytest.approx(down["score"])


def test_price_event_is_capped_at_weight():
    result = score_of(
        metrics(trend="NEUTRAL"),
        ["LARGE_MOVE", "NEW_20D_HIGH", "NEW_20D_LOW", "OVERBOUGHT", "OVERSOLD", "HIGH_VOLUME"],
    )
    event = next(c for c in result["components"] if c["key"] == "price_event")
    assert event["points"] == pytest.approx(15.0)   # 6 个标签 × 50% 封顶 100%
    assert event["max_points"] == pytest.approx(15.0)


def test_high_volume_is_not_counted_as_price_event():
    result = score_of(metrics(volume_ratio=1.0), ["HIGH_VOLUME"])
    event = next(c for c in result["components"] if c["key"] == "price_event")
    assert event["points"] == pytest.approx(0.0)
    assert "无价格事件标签" in event["reason"]


def test_volume_component_is_linear_between_baseline_and_full_credit():
    result = score_of(metrics(volume_ratio=1.75))  # (1.75-1)/(2.5-1) = 0.5 → 7.5 分
    volume = next(c for c in result["components"] if c["key"] == "volume_activity")
    assert volume["points"] == pytest.approx(7.5)


def test_missing_relative_strength_scores_zero_and_says_why():
    result = score_of(metrics(**{RS_KEY: None}))
    rs = next(c for c in result["components"] if c["key"] == "relative_strength")
    assert rs["points"] == pytest.approx(0.0)
    assert "n/a" in rs["reason"]


def test_insufficient_data_trend_scores_zero():
    result = score_of(metrics(trend="INSUFFICIENT_DATA"))
    trend = next(c for c in result["components"] if c["key"] == "trend")
    assert trend["points"] == pytest.approx(0.0)
    assert "无法判定" in trend["reason"]


def test_disabled_returns_none():
    result = attention_score(metrics(), [], {**SCORE_CFG, "enabled": False})
    assert result["enabled"] is False
    assert result["score"] is None
    assert result["components"] == []


def test_evidence_strings_are_present():
    result = score_of(metrics(trend="UPTREND", return_20d_pct=4.2, volume_ratio=2.1, **{RS_KEY: 5.5}), ["LARGE_MOVE"])
    for component in result["components"]:
        assert component["reason"], component
    assert "+4.2%" in next(c for c in result["components"] if c["key"] == "momentum_20d")["reason"]
