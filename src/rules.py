"""趋势分类与异常标签：deterministic rules，由 Python 决定，不由 LLM 决定（spec §5）。

这些标签只**描述状态**，刻意不做成 RSI<30 → BUY 这类买卖信号：
规则表达的是「现在发生了什么」，不是「明天会怎样」。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

TREND_STRONG_UPTREND = "STRONG_UPTREND"
TREND_UPTREND = "UPTREND"
TREND_NEUTRAL = "NEUTRAL"
TREND_DOWNTREND = "DOWNTREND"
TREND_STRONG_DOWNTREND = "STRONG_DOWNTREND"
TREND_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

TREND_DISPLAY = {
    TREND_STRONG_UPTREND: "Strong Uptrend 强上升",
    TREND_UPTREND: "Uptrend 上升",
    TREND_NEUTRAL: "Neutral 中性",
    TREND_DOWNTREND: "Downtrend 下降",
    TREND_STRONG_DOWNTREND: "Strong Downtrend 强下降",
    TREND_INSUFFICIENT_DATA: "Insufficient Data 数据不足",
}

ALERT_HIGH_VOLUME = "HIGH_VOLUME"
ALERT_LARGE_MOVE = "LARGE_MOVE"
ALERT_OVERBOUGHT = "OVERBOUGHT"
ALERT_OVERSOLD = "OVERSOLD"
ALERT_NEW_20D_HIGH = "NEW_20D_HIGH"
ALERT_NEW_20D_LOW = "NEW_20D_LOW"

ALERT_ORDER = [
    ALERT_LARGE_MOVE,
    ALERT_HIGH_VOLUME,
    ALERT_NEW_20D_HIGH,
    ALERT_NEW_20D_LOW,
    ALERT_OVERBOUGHT,
    ALERT_OVERSOLD,
]


def classify_trend(metrics: Mapping[str, Any]) -> str:
    """按 spec §5 的优先级判定趋势。

        Strong Uptrend:    Close > SMA20 > SMA50 > SMA200
        Strong Downtrend:  Close < SMA20 < SMA50 < SMA200
        Uptrend:           Close > SMA20 AND Close > SMA50
        Downtrend:         Close < SMA20 AND Close < SMA50
        Neutral:           其余

    SMA20 / SMA50 不可用（历史太短）时返回 INSUFFICIENT_DATA —— 不猜。
    SMA200 不可用时无法判「强」，降级到 Uptrend/Downtrend/Neutral。
    """
    close = metrics.get("close")
    sma20 = metrics.get("sma20")
    sma50 = metrics.get("sma50")
    sma200 = metrics.get("sma200")

    if close is None or sma20 is None or sma50 is None:
        return TREND_INSUFFICIENT_DATA

    if sma200 is not None:
        if close > sma20 > sma50 > sma200:
            return TREND_STRONG_UPTREND
        if close < sma20 < sma50 < sma200:
            return TREND_STRONG_DOWNTREND

    if close > sma20 and close > sma50:
        return TREND_UPTREND
    if close < sma20 and close < sma50:
        return TREND_DOWNTREND
    return TREND_NEUTRAL


def detect_alerts(metrics: Mapping[str, Any], thresholds: Mapping[str, Any] | None = None) -> list[str]:
    """按 spec §5 的阈值生成异常标签（只描述状态，不是买卖信号）。"""
    th = dict(thresholds or {})
    high_volume_ratio = float(th.get("high_volume_ratio", 2.0))
    large_move_pct = float(th.get("large_move_pct", 4.0))
    rsi_overbought = float(th.get("rsi_overbought", 70))
    rsi_oversold = float(th.get("rsi_oversold", 30))

    close = metrics.get("close")
    volume_ratio = metrics.get("volume_ratio")
    daily_return = metrics.get("return_1d_pct")
    rsi14 = metrics.get("rsi14")
    prev_high = metrics.get("prev_20d_high")
    prev_low = metrics.get("prev_20d_low")

    alerts: list[str] = []
    if daily_return is not None and abs(daily_return) >= large_move_pct:
        alerts.append(ALERT_LARGE_MOVE)
    if volume_ratio is not None and volume_ratio >= high_volume_ratio:
        alerts.append(ALERT_HIGH_VOLUME)
    if close is not None and prev_high is not None and close >= prev_high:
        alerts.append(ALERT_NEW_20D_HIGH)
    if close is not None and prev_low is not None and close <= prev_low:
        alerts.append(ALERT_NEW_20D_LOW)
    if rsi14 is not None and rsi14 >= rsi_overbought:
        alerts.append(ALERT_OVERBOUGHT)
    if rsi14 is not None and rsi14 <= rsi_oversold:
        alerts.append(ALERT_OVERSOLD)

    return [alert for alert in ALERT_ORDER if alert in alerts]


def alert_details(alerts: Sequence[str], metrics: Mapping[str, Any], decimals: int = 2) -> list[str]:
    """给每个 alert 附上触发依据，例如 `LARGE_MOVE (1D -5.20%)`。

    「为什么今天标了它」必须能当场核对，否则标签就是玄学。
    """
    details: list[str] = []
    for alert in alerts:
        value = metrics.get("return_1d_pct")
        if alert == ALERT_LARGE_MOVE:
            details.append(f"{alert} (1D {_pct(value, decimals)})")
        elif alert == ALERT_HIGH_VOLUME:
            details.append(f"{alert} (量比 {_num(metrics.get('volume_ratio'), decimals)}x)")
        elif alert == ALERT_OVERBOUGHT:
            details.append(f"{alert} (RSI14 {_num(metrics.get('rsi14'), 1)})")
        elif alert == ALERT_OVERSOLD:
            details.append(f"{alert} (RSI14 {_num(metrics.get('rsi14'), 1)})")
        elif alert == ALERT_NEW_20D_HIGH:
            details.append(
                f"{alert} (Close {_num(metrics.get('close'), decimals)} >= 前 20 日最高 "
                f"{_num(metrics.get('prev_20d_high'), decimals)})"
            )
        elif alert == ALERT_NEW_20D_LOW:
            details.append(
                f"{alert} (Close {_num(metrics.get('close'), decimals)} <= 前 20 日最低 "
                f"{_num(metrics.get('prev_20d_low'), decimals)})"
            )
        else:  # 未知标签也照原样输出，不要让日报缺一块
            details.append(str(alert))
    return details


def _pct(value: Any, decimals: int) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):+.{decimals}f}%"


def _num(value: Any, decimals: int) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.{decimals}f}"
