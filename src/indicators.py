"""技术指标计算：全部用 pandas/numpy 手写（spec §10：不堆一篮子 TA 库）。

口径说明（会原样写进日报的「指标口径」小节，方便手工核对）：
* 收益率（1D/5D/20D/60D）用**复权收盘价 Adj Close** 计算（spec §3：adjusted data 用于历史收益计算）；
  SMA / RSI / 旧版「距近期高点」/ 新高新低用**原始收盘价 Close**，这样日报里的 Close 和公开行情页面一致。
* 252D 风险指标使用与收益率相同的价格序列（优先 Adj Close），避免拆股等 corporate actions 制造虚假回撤。
* Volume Ratio = 今日成交量 / 今日之前 N 个交易日的平均成交量（不含今日，避免自我稀释）。
* RSI14 用 Wilder 平滑（EMA α = 1/14）。
* Volatility 20D = 最近 20 个交易日日收益率的标准差（同时给日频和年化两个口径）。
* Drawdown = 当前 Close 相对最近 N 个交易日最高收盘价的回撤（负数）。
* NEW_20D_HIGH / LOW 的「前 20 日」不含今日。

所有函数在数据不足时返回 None —— 绝不返回 NaN，也不猜数字（spec §12「指标没有 NaN 灾难」）。
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------


def clean_number(value: Any) -> float | None:
    """NaN / inf / None / 不可转换 → None。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _as_float_series(data: Any) -> pd.Series | None:
    if data is None:
        return None
    series = data if isinstance(data, pd.Series) else pd.Series(data)
    if len(series) == 0:
        return None
    series = series.astype("float64")
    return series if series.notna().any() else None


def _round(value: Any, decimals: int | None) -> float | None:
    number = clean_number(value)
    if number is None:
        return None
    return number if decimals is None else round(number, decimals)


# ---------------------------------------------------------------------------
# 单指标
# ---------------------------------------------------------------------------


def pct_change_over(series: Any, window: int) -> float | None:
    """最近 `window` 个交易日的涨跌幅（百分比）。需要 window + 1 个数据点。"""
    s = _as_float_series(series)
    if s is None or window < 1 or len(s) < window + 1:
        return None
    start = clean_number(s.iloc[-window - 1])
    end = clean_number(s.iloc[-1])
    if start is None or end is None or start == 0:
        return None
    return (end / start - 1.0) * 100.0


def simple_moving_average(series: Any, window: int) -> float | None:
    """最近 `window` 个数据点的简单移动平均。数据不足返回 None。"""
    s = _as_float_series(series)
    if s is None or window < 1 or len(s) < window:
        return None
    window_slice = s.iloc[-window:]
    if window_slice.isna().any():  # 窗口内有空洞 → 不硬算
        return None
    return clean_number(window_slice.mean())


def rsi_wilder(series: Any, period: int = 14) -> pd.Series | None:
    """Wilder RSI 序列。价格完全不动时约定为 50（中性），而不是 NaN。"""
    s = _as_float_series(series)
    if s is None or len(s) < period + 1:
        return None

    delta = s.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    alpha = 1.0 / float(period)
    avg_gain = gain.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=alpha, adjust=False, min_periods=period).mean()

    valid = avg_gain.notna() & avg_loss.notna()
    safe_loss = avg_loss.where(avg_loss > 0)
    rs = avg_gain.where(avg_loss > 0) / safe_loss
    out = 100.0 - 100.0 / (1.0 + rs)
    # avg_loss == 0：只涨不跌 → 100；完全不涨不跌 → 50
    out = out.mask(valid & (avg_loss <= 0) & (avg_gain > 0), 100.0)
    out = out.mask(valid & (avg_loss <= 0) & (avg_gain <= 0), 50.0)
    return out.mask(~valid)


def rsi_last(series: Any, period: int = 14) -> float | None:
    """最近一个交易日的 RSI14。"""
    values = rsi_wilder(series, period)
    if values is None:
        return None
    return clean_number(values.iloc[-1])


def volume_ratio(volume: Any, window: int = 20) -> float | None:
    """今日成交量 / 今日之前 `window` 个交易日的平均成交量。"""
    v = _as_float_series(volume)
    if v is None or window < 1 or len(v) < window + 1:
        return None
    baseline = v.iloc[-window - 1 : -1]
    if baseline.isna().any():
        return None
    average = clean_number(baseline.mean())
    today = clean_number(v.iloc[-1])
    if average is None or today is None or average == 0:
        return None
    return today / average


def volatility(daily_returns: Any, window: int = 20, trading_days_per_year: int = 252) -> tuple[float | None, float | None]:
    """最近 `window` 个日收益率的标准差。返回 (日频 %, 年化 %)。"""
    returns = _as_float_series(daily_returns)
    if returns is None:
        return None, None
    returns = returns.dropna()
    if len(returns) < max(2, window):
        return None, None
    recent = returns.iloc[-window:]
    std = recent.std(ddof=1)
    daily_pct = clean_number(std * 100.0)
    annualized_pct = clean_number(std * math.sqrt(trading_days_per_year) * 100.0)
    return daily_pct, annualized_pct


def drawdown_from_high(series: Any, lookback: int = 252) -> dict[str, Any]:
    """当前价相对最近 `lookback` 个交易日内最高收盘价的回撤。

    lookback 超过可用行数时自动收缩到可用行数，并在 lookback_used 里说明实际用了多久。
    """
    s = _as_float_series(series)
    if s is None:
        return {"drawdown_from_high_pct": None, "recent_high": None, "recent_high_date": None, "lookback_used": 0}
    s = s.dropna()
    if len(s) < 2:
        return {"drawdown_from_high_pct": None, "recent_high": None, "recent_high_date": None, "lookback_used": len(s)}

    used = min(int(lookback), len(s))
    window_slice = s.iloc[-used:]
    high = clean_number(window_slice.max())
    last = clean_number(window_slice.iloc[-1])
    drawdown = None
    if high not in (None, 0) and last is not None:
        drawdown = (last / high - 1.0) * 100.0
    return {
        "drawdown_from_high_pct": drawdown,
        "recent_high": high,
        "recent_high_date": _date_str(window_slice.idxmax()),
        "lookback_used": used,
    }


def risk_metrics(
    series: Any,
    *,
    window: int = 252,
    annual_risk_free_rate: float = 0.0,
    trading_days_per_year: int = 252,
) -> dict[str, Any]:
    """严格计算历史风险指标，不用短窗口冒充完整窗口。

    ``window`` 个日收益需要 ``window + 1`` 个连续有效价格点。回撤使用其中
    最后 ``window`` 个价格点；Sharpe 使用完整的 ``window`` 个日收益。
    """
    result: dict[str, Any] = {
        "risk_status": "DATA_INSUFFICIENT",
        "risk_window_trading_days": int(window),
        "risk_free_rate_annual_pct": clean_number(float(annual_risk_free_rate) * 100.0),
        "current_drawdown_252d_pct": None,
        "max_drawdown_252d_pct": None,
        "sharpe_252d": None,
    }
    if window < 2 or trading_days_per_year < 1 or annual_risk_free_rate <= -1.0:
        return result

    prices = _as_float_series(series)
    if prices is None or len(prices) < window + 1:
        return result
    sample = prices.iloc[-window - 1 :]
    if sample.isna().any() or (sample <= 0).any():
        return result

    drawdown_prices = sample.iloc[-window:]
    drawdowns = drawdown_prices / drawdown_prices.cummax() - 1.0
    daily_returns = sample.pct_change(fill_method=None).iloc[1:]
    if len(daily_returns) != window or daily_returns.isna().any():
        return result

    current_drawdown = clean_number(drawdowns.iloc[-1] * 100.0)
    maximum_drawdown = clean_number(drawdowns.min() * 100.0)
    daily_rf = (1.0 + float(annual_risk_free_rate)) ** (1.0 / float(trading_days_per_year)) - 1.0
    excess_returns = daily_returns - daily_rf
    std = clean_number(excess_returns.std(ddof=1))
    sharpe = None
    if std is not None and std > 0:
        sharpe = clean_number(excess_returns.mean() / std * math.sqrt(trading_days_per_year))

    result.update(
        {
            "risk_status": "OK",
            "current_drawdown_252d_pct": current_drawdown,
            "max_drawdown_252d_pct": maximum_drawdown,
            "sharpe_252d": sharpe,
        }
    )
    return result


def previous_window_extremes(series: Any, window: int = 20) -> tuple[float | None, float | None]:
    """今日之前 `window` 个交易日的最高/最低收盘价（不含今日）。数据不足返回 (None, None)。"""
    s = _as_float_series(series)
    if s is None or window < 1 or len(s) < window + 1:
        return None, None
    previous = s.iloc[-window - 1 : -1].dropna()
    if len(previous) < window:
        return None, None
    return clean_number(previous.max()), clean_number(previous.min())


def _date_str(value: Any) -> str | None:
    try:
        stamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(stamp):
        return None
    return stamp.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# 一只股票的完整指标
# ---------------------------------------------------------------------------


def summarize(df: pd.DataFrame, settings, *, decimals: int = 6) -> dict[str, Any]:
    """把单只股票的 OHLCV 汇总成一份指标 dict。

    返回的字典会一路传到 rules / scoring / report / 输出文件，是唯一的事实来源。
    任何算不出来的指标都是 None。
    """
    indicators_cfg = settings.section("indicators")
    sma_windows: Sequence[int] = indicators_cfg.get("sma_windows", [20, 50, 200])
    return_windows: Sequence[int] = indicators_cfg.get("return_windows", [1, 5, 20, 60])
    rsi_period = int(indicators_cfg.get("rsi_period", 14))
    volume_window = int(indicators_cfg.get("volume_window", 20))
    volatility_window = int(indicators_cfg.get("volatility_window", 20))
    trading_days = int(indicators_cfg.get("trading_days_per_year", 252))
    drawdown_lookback = int(indicators_cfg.get("drawdown_lookback_days", 252))
    new_high_low_window = int(indicators_cfg.get("new_high_low_window", 20))
    risk_cfg = settings.section("risk")
    risk_window = int(risk_cfg.get("window", 252))
    annual_risk_free_rate = float(risk_cfg.get("annual_risk_free_rate", 0.0))

    close = df["Close"].astype("float64")
    adj_close = df["Adj Close"].astype("float64") if "Adj Close" in df.columns else None
    if adj_close is None or adj_close.dropna().empty:
        adj_close = close  # 数据源没给复权价就退回原始价，并在下面标注
        used_adjusted = False
    else:
        used_adjusted = True
    volume = df["Volume"].astype("float64") if "Volume" in df.columns else None

    daily_returns = adj_close.pct_change(fill_method=None)
    vol_daily, vol_annual = volatility(daily_returns, volatility_window, trading_days)
    drawdown = drawdown_from_high(close, drawdown_lookback)
    risk = risk_metrics(
        adj_close,
        window=risk_window,
        annual_risk_free_rate=annual_risk_free_rate,
        trading_days_per_year=trading_days,
    )
    prev_high, prev_low = previous_window_extremes(close, new_high_low_window)

    metrics: dict[str, Any] = {
        # 元信息
        "date": _date_str(df.index[-1]),
        "history_rows": int(len(df)),
        "returns_basis": "adj_close" if used_adjusted else "close",
        # 价格
        "close": _round(close.iloc[-1], decimals),
        "adjusted_close": _round(adj_close.iloc[-1], decimals),
        # 收益率（复权价）
        "return_1d_pct": None,  # 占位，下面按 config 的 return_windows 覆盖
        # 动量 / 波动 / 成交量（原始价口径）
        "rsi14": _round(rsi_last(close, rsi_period), decimals),
        "volume": _round(volume.iloc[-1], decimals) if volume is not None else None,
        "volume_ratio": _round(volume_ratio(volume, volume_window), decimals),
        "volatility_20d_daily_pct": _round(vol_daily, decimals),
        "volatility_20d_annualized_pct": _round(vol_annual, decimals),
        "drawdown_from_high_pct": _round(drawdown["drawdown_from_high_pct"], decimals),
        "recent_high": _round(drawdown["recent_high"], decimals),
        "recent_high_date": drawdown["recent_high_date"],
        "drawdown_lookback_used": int(drawdown["lookback_used"]),
        "prev_20d_high": _round(prev_high, decimals),
        "prev_20d_low": _round(prev_low, decimals),
        "new_high_low_window": new_high_low_window,
        "volume_window": volume_window,
        # 数据可用性
        "sma200_available": False,
        "notes": [],
        **risk,
    }

    for window in return_windows:
        metrics[f"return_{int(window)}d_pct"] = _round(pct_change_over(adj_close, int(window)), decimals)

    for window in sma_windows:
        metrics[f"sma{int(window)}"] = _round(simple_moving_average(close, int(window)), decimals)

    if metrics.get("sma200") is None:
        metrics["notes"].append(f"历史不足 200 个交易日（{metrics['history_rows']} 行），SMA200 不可用")
    else:
        metrics["sma200_available"] = True
    if not used_adjusted:
        metrics["notes"].append("数据源未提供复权价，收益率用原始 Close 计算")
    if metrics["risk_status"] == "DATA_INSUFFICIENT":
        metrics["notes"].append(
            f"风险指标数据不足：需要 {risk_window + 1} 个有效价格点计算 {risk_window} 个日收益"
        )

    return metrics
