"""Attention Score 0–100（spec §6）：今天值不值得打开看一眼。

* 不是「买入评分」，不是预期收益，也不代表看涨：强上涨和强下跌都给高分。
* 权重全部来自 config.yaml（attention_score 段），代码里不硬编码。
* 输出必须保留**分数构成**：总分 = 各分项之和（分项各自四舍五入到 1 位），
  所以爸爸问「为什么 82」时能逐项对上，而不是「AI 感觉它今天气色不错」。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .rules import TREND_INSUFFICIENT_DATA

COMPONENT_LABELS = {
    "trend": "Trend 趋势",
    "momentum_20d": "Momentum 20D 中期动量",
    "relative_strength": "Relative Strength vs 基准",
    "volume_activity": "Volume Activity 成交量异动",
    "price_event": "Price Event 价格事件",
}


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _ratio_of(value: Any, full_credit: float) -> float:
    """|value| / full_credit，截断到 [0,1]。value 不可用或 full_credit <= 0 → 0。"""
    if value is None or full_credit <= 0:
        return 0.0
    return _clamp(abs(float(value)) / float(full_credit))


def _points(achievement: float, weight: float, decimals: int) -> float:
    return round(achievement * weight, decimals)


def attention_score(
    metrics: Mapping[str, Any],
    alerts: Sequence[str],
    score_config: Mapping[str, Any] | None,
    *,
    relative_strength_window: int = 20,
    benchmark: str = "QQQ",
    decimals: int = 1,
) -> dict[str, Any]:
    """计算 Attention Score 及其构成。返回字典，永远不带 NaN。"""
    cfg = dict(score_config or {})
    if not cfg.get("enabled", True):
        return {"enabled": False, "score": None, "max_score": None, "components": []}

    components: list[dict[str, Any]] = []

    # --- Trend：离中性越远越值得看（多空方向都算）---
    trend_cfg = dict(cfg.get("trend") or {})
    trend_weight = float(trend_cfg.get("weight", 0) or 0)
    trend_scores = dict(trend_cfg.get("scores") or {})
    trend = metrics.get("trend") or TREND_INSUFFICIENT_DATA
    trend_ratio = float(trend_scores.get(trend, 0.0) or 0.0)
    reason = f"{trend}"
    if trend == TREND_INSUFFICIENT_DATA:
        reason = f"{trend}（历史不足，趋势无法判定）"
    components.append(_component("trend", trend_ratio, trend_weight, reason, decimals))

    # --- 20D 动量 ---
    momentum_cfg = dict(cfg.get("momentum_20d") or {})
    momentum_weight = float(momentum_cfg.get("weight", 0) or 0)
    full_r20 = float(momentum_cfg.get("full_credit_abs_return_pct", 0) or 0)
    r20 = metrics.get("return_20d_pct")
    momentum_ratio = _ratio_of(r20, full_r20)
    components.append(
        _component(
            "momentum_20d",
            momentum_ratio,
            momentum_weight,
            "20D 收益 n/a" if r20 is None else f"20D 收益 {float(r20):+.1f}%（满分线 ±{full_r20:.0f}%）",
            decimals,
        )
    )

    # --- 相对基准强弱 ---
    rs_cfg = dict(cfg.get("relative_strength") or {})
    rs_weight = float(rs_cfg.get("weight", 0) or 0)
    full_rs = float(rs_cfg.get("full_credit_abs_diff_pct", 0) or 0)
    rs_key = f"relative_strength_{int(relative_strength_window)}d_vs_{str(benchmark).lower()}"
    rs_value = metrics.get(rs_key)
    rs_ratio = _ratio_of(rs_value, full_rs)
    components.append(
        _component(
            "relative_strength",
            rs_ratio,
            rs_weight,
            f"vs {benchmark} n/a" if rs_value is None else f"vs {benchmark} {float(rs_value):+.1f}%（满分线 ±{full_rs:.0f}%）",
            decimals,
        )
    )

    # --- 成交量异动 ---
    volume_cfg = dict(cfg.get("volume_activity") or {})
    volume_weight = float(volume_cfg.get("weight", 0) or 0)
    baseline_ratio = float(volume_cfg.get("baseline_ratio", 1.0) or 0)
    full_ratio = float(volume_cfg.get("full_credit_ratio", 0) or 0)
    volume_ratio_value = metrics.get("volume_ratio")
    if volume_ratio_value is None or full_ratio <= baseline_ratio:
        volume_achievement = 0.0
        volume_reason = "量比 n/a"
    else:
        volume_achievement = _clamp((float(volume_ratio_value) - baseline_ratio) / (full_ratio - baseline_ratio))
        volume_reason = f"量比 {float(volume_ratio_value):.2f}x（{baseline_ratio:.1f}x 起计，{full_ratio:.1f}x 满分）"
    components.append(_component("volume_activity", volume_achievement, volume_weight, volume_reason, decimals))

    # --- 价格事件 ---
    event_cfg = dict(cfg.get("price_event") or {})
    event_weight = float(event_cfg.get("weight", 0) or 0)
    per_alert = float(event_cfg.get("per_alert_credit", 0) or 0)
    event_alerts = [str(a) for a in (event_cfg.get("alerts") or [])]
    matched = [alert for alert in alerts if alert in event_alerts]
    event_achievement = _clamp(len(matched) * per_alert)
    event_reason = "、".join(matched) if matched else "无价格事件标签"
    if matched:
        event_reason = f"{event_reason}（每个 {int(per_alert * 100)}%，封顶 100%）"
    components.append(_component("price_event", event_achievement, event_weight, event_reason, decimals))

    total = round(sum(component["points"] for component in components), decimals)
    max_score = round(sum(component["max_points"] for component in components), decimals)
    return {"enabled": True, "score": total, "max_score": max_score, "components": components}


def _component(key: str, achievement: float, weight: float, reason: str, decimals: int) -> dict[str, Any]:
    return {
        "key": key,
        "label": COMPONENT_LABELS.get(key, key),
        "achievement": round(float(achievement), 4),
        "points": _points(achievement, weight, decimals),
        "max_points": round(float(weight), decimals),
        "reason": reason,
    }
