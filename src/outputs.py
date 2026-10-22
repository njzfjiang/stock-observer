"""产出文件（spec §7）：

    outputs/daily_report.md     给人类看
    outputs/analysis_input.json 给 AI 读（结构化，禁止模型自己补数据）
    outputs/raw_metrics.csv     给 Excel / debug

JSON 里每只股票的键名严格照 spec §7 的示例（ticker / date / close / return_1d_pct /
return_20d_pct / sma20 / sma50 / sma200 / rsi14 / volume_ratio /
relative_strength_20d_vs_qqq / trend / alerts），另外附上更多字段和口径说明。
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from .rules import ALERT_ORDER, TREND_DISPLAY

# CSV / JSON 里每只股票的必要字段（顺序即 CSV 列顺序）
METRIC_COLUMNS: list[str] = [
    "ticker",
    "status",
    "status_reason",
    "date",
    "close",
    "adjusted_close",
    "returns_basis",
    "return_1d_pct",
    "return_5d_pct",
    "return_20d_pct",
    "return_60d_pct",
    "sma20",
    "sma50",
    "sma200",
    "sma200_available",
    "rsi14",
    "volume",
    "volume_ratio",
    "volatility_20d_daily_pct",
    "volatility_20d_annualized_pct",
    "drawdown_from_high_pct",
    "recent_high",
    "recent_high_date",
    "drawdown_lookback_used",
    "risk_status",
    "risk_window_trading_days",
    "risk_free_rate_annual_pct",
    "current_drawdown_252d_pct",
    "max_drawdown_252d_pct",
    "sharpe_252d",
    "prev_20d_high",
    "prev_20d_low",
    "relative_strength_20d_vs_qqq",
    "trend",
    "alerts",
    "alert_details",
    "attention_score",
    "attention_score_max",
    "news_status",
    "news_article_count_24h",
    "news_positive_count",
    "news_neutral_count",
    "news_negative_count",
    "news_sentiment_score_24h",
    "news_sentiment_label_24h",
    "history_rows",
    "notes",
]

SCORE_COLUMN_PREFIX = "score_"

# 每只股票 JSON 里必须出现的键（spec §7 示例 + 关注度构成）
JSON_TICKER_KEYS: list[str] = [
    "ticker",
    "date",
    "close",
    "return_1d_pct",
    "return_20d_pct",
    "sma20",
    "sma50",
    "sma200",
    "rsi14",
    "volume_ratio",
    "relative_strength_20d_vs_qqq",
    "trend",
    "alerts",
]


def score_columns(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """按实际出现的分项收集 score_* 列名（保持 config 里的分项顺序）。"""
    ordered: list[str] = []
    for row in rows:
        for component in row.get("attention_components") or []:
            column = f"{SCORE_COLUMN_PREFIX}{component.get('key')}"
            if column not in ordered:
                ordered.append(column)
    return ordered


def rs_column(settings) -> str:
    """相对强弱列名随 config 的窗口/基准变化，例如 relative_strength_20d_vs_qqq。"""
    window = int(settings.get("indicators", "relative_strength_window", default=20))
    benchmark = str(settings.get("project", "benchmark", default="QQQ")).lower()
    return f"relative_strength_{window}d_vs_{benchmark}"


def metric_columns(settings) -> list[str]:
    """CSV 列顺序：把占位的 relative_strength_20d_vs_qqq 换成实际列名。"""
    actual = rs_column(settings)
    return [actual if column == "relative_strength_20d_vs_qqq" else column for column in METRIC_COLUMNS]


def _csv_value(value: Any) -> Any:
    """把 list / bool / None 转成 CSV 友好的值。"""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ";".join(str(item) for item in value)
    return value


def write_raw_metrics_csv(path: Path, rows: Sequence[Mapping[str, Any]], failures: Mapping[str, str], settings) -> Path:
    """全部原始指标，一行一只股票；失败标的也占一行（status = DATA_UNAVAILABLE）。"""
    columns = metric_columns(settings) + score_columns(rows)
    records: list[dict[str, Any]] = []

    for row in rows:
        record = {column: _csv_value(row.get(column)) for column in columns}
        record["status"] = row.get("status", "OK")
        news = row.get("news") if isinstance(row.get("news"), dict) else {}
        record.update(
            {
                "news_status": _csv_value(news.get("status")),
                "news_article_count_24h": _csv_value(news.get("article_count_24h")),
                "news_positive_count": _csv_value(news.get("positive_count")),
                "news_neutral_count": _csv_value(news.get("neutral_count")),
                "news_negative_count": _csv_value(news.get("negative_count")),
                "news_sentiment_score_24h": _csv_value(news.get("sentiment_score_24h")),
                "news_sentiment_label_24h": _csv_value(news.get("sentiment_label_24h")),
            }
        )
        for component in row.get("attention_components") or []:
            record[f"{SCORE_COLUMN_PREFIX}{component.get('key')}"] = _csv_value(component.get("points"))
        records.append(record)

    for ticker, reason in failures.items():
        record = {column: "" for column in columns}
        record.update(
            {
                "ticker": ticker,
                "status": "DATA_UNAVAILABLE",
                "status_reason": reason,
            }
        )
        records.append(record)

    frame = pd.DataFrame(records, columns=columns)
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig：Excel 直接双击打开不乱码
    frame.to_csv(path, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)
    return path


def build_analysis_input(
    *,
    rows: Sequence[Mapping[str, Any]],
    failures: Mapping[str, str],
    settings,
    generated_at: str,
    data_as_of: str | None,
    benchmark: str,
    market_tickers: Sequence[str],
    watchlist_size: int,
    period: str,
    interval: str,
    news: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """构造喂给 AI 的结构化 JSON（Python 是事实层，ChatGPT 是解释层）。"""
    thresholds = dict(settings.section("thresholds"))
    score_cfg = settings.section("attention_score")

    tickers: list[dict[str, Any]] = []
    rs_key = rs_column(settings)
    for row in rows:
        payload: dict[str, Any] = {key: row.get(key) for key in JSON_TICKER_KEYS}
        # spec §7 里写的键名固定是 relative_strength_20d_vs_qqq；
        # 如果 config 改了窗口/基准，就把实际列名的值映射到这个名字上，并注明真实列名。
        payload["relative_strength_20d_vs_qqq"] = row.get(rs_key)
        payload["relative_strength_column"] = rs_key
        payload["alerts"] = list(row.get("alerts") or [])
        payload.update(
            {
                "status": "OK",
                "adjusted_close": row.get("adjusted_close"),
                "return_5d_pct": row.get("return_5d_pct"),
                "return_60d_pct": row.get("return_60d_pct"),
                "volatility_20d_annualized_pct": row.get("volatility_20d_annualized_pct"),
                "volatility_20d_daily_pct": row.get("volatility_20d_daily_pct"),
                "drawdown_from_high_pct": row.get("drawdown_from_high_pct"),
                "risk": {
                    "status": row.get("risk_status"),
                    "window_trading_days": row.get("risk_window_trading_days"),
                    "current_drawdown_pct": row.get("current_drawdown_252d_pct"),
                    "max_drawdown_pct": row.get("max_drawdown_252d_pct"),
                    "sharpe_ratio": row.get("sharpe_252d"),
                    "risk_free_rate_annual_pct": row.get("risk_free_rate_annual_pct"),
                },
                "recent_high": row.get("recent_high"),
                "recent_high_date": row.get("recent_high_date"),
                "prev_20d_high": row.get("prev_20d_high"),
                "prev_20d_low": row.get("prev_20d_low"),
                "volume": row.get("volume"),
                "history_rows": row.get("history_rows"),
                "alert_details": list(row.get("alert_details") or []),
                "attention_score": row.get("attention_score"),
                "attention_score_max": row.get("attention_score_max"),
                "attention_score_breakdown": [
                    {
                        "component": component.get("key"),
                        "points": component.get("points"),
                        "max_points": component.get("max_points"),
                        "evidence": component.get("reason"),
                    }
                    for component in (row.get("attention_components") or [])
                ],
                "notes": list(row.get("notes") or []),
                "news": dict(row.get("news") or {}),
            }
        )
        tickers.append(payload)

    return {
        "generated_at": generated_at,
        "data_as_of": data_as_of,
        "data_source": f"Yahoo Finance via yfinance (period={period}, interval={interval}, auto_adjust=False)",
        "currency": "USD",
        "benchmark": benchmark,
        "market_tickers": [str(t).upper() for t in market_tickers],
        "watchlist_size": int(watchlist_size),
        "ticker_count_ok": len(tickers),
        "ticker_count_failed": len(failures),
        "thresholds": thresholds,
        "attention_score_weights": {
            key: value.get("weight")
            for key, value in score_cfg.items()
            if isinstance(value, dict) and "weight" in value
        },
        "risk_parameters": {
            "window_trading_days": int(settings.get("risk", "window", default=252)),
            "annual_risk_free_rate": float(settings.get("risk", "annual_risk_free_rate", default=0.0)),
            "risk_free_rate_annual_pct": float(settings.get("risk", "annual_risk_free_rate", default=0.0)) * 100.0,
        },
        "news": dict(news or {}),
        "field_notes": _field_notes(benchmark, thresholds, settings),
        "disclaimer": (
            "本文件由 Python 规则引擎确定性生成，只包含已观测到的历史行情与派生指标。"
            "系统定位为市场监控/数据摘要工具，不是自动交易系统，也不是投资顾问；"
            "所有标签只描述当前状态，不构成买入或卖出建议。"
        ),
        "tickers": tickers,
        "data_unavailable": [
            {"ticker": ticker, "status": "DATA_UNAVAILABLE", "reason": reason}
            for ticker, reason in failures.items()
        ],
    }


def _field_notes(benchmark: str, thresholds: Mapping[str, Any], settings) -> dict[str, str]:
    risk_window = int(settings.get("risk", "window", default=252))
    risk_free_pct = float(settings.get("risk", "annual_risk_free_rate", default=0.0)) * 100.0
    return {
        "return_1d_pct": "1 个交易日涨跌幅，百分比；用复权收盘价计算。",
        "return_5d_pct / return_20d_pct / return_60d_pct": "对应交易日窗口的涨跌幅，百分比；用复权收盘价计算。",
        "close": "最新交易日原始收盘价（与公开行情页面一致）；sma20/50/200 与它同口径。",
        "relative_strength_20d_vs_qqq": f"20 个交易日收益减去 {benchmark} 同期收益（百分点），正数表示跑赢基准。",
        "rsi14": "Wilder 平滑的 14 日 RSI，0-100；>= overbought 记为 OVERBOUGHT，<= oversold 记为 OVERSOLD，仅描述状态。",
        "volume_ratio": "最新交易日成交量 ÷ 今日之前 20 个交易日的平均成交量。",
        "volatility_20d_annualized_pct": "最近 20 个交易日日收益率标准差 × √252，年化百分比。",
        "drawdown_from_high_pct": "最新收盘价相对最近约 252 个交易日最高收盘价的回撤，负数表示低于高点。",
        "risk": (
            f"历史风险指标使用复权价和严格 {risk_window} 日收益窗口；年化无风险利率假设为 {risk_free_pct:g}%。"
            "数据不足时 status=DATA_INSUFFICIENT 且指标为 null；波动率为 0 时 Sharpe 为 null。"
        ),
        "trend": "由规则判定的趋势：STRONG_UPTREND / UPTREND / NEUTRAL / DOWNTREND / STRONG_DOWNTREND / INSUFFICIENT_DATA。",
        "alerts": "异常状态标签（只描述状态，不是买卖信号）：" + "、".join(ALERT_ORDER) + "。",
        "thresholds_used": (
            f"HIGH_VOLUME 量比 >= {thresholds.get('high_volume_ratio')}；"
            f"LARGE_MOVE |1D| >= {thresholds.get('large_move_pct')}%；"
            f"OVERBOUGHT RSI14 >= {thresholds.get('rsi_overbought')}；"
            f"OVERSOLD RSI14 <= {thresholds.get('rsi_oversold')}。"
        ),
        "attention_score": "0-100 的「今天值不值得打开看一眼」评分，由趋势/动量/相对强弱/量能/价格事件加权而成（attention_score_breakdown 给出逐项证据）。分数高不等于看涨。",
        "data_unavailable": "抓取失败的标的。禁止推测或补全其数值，只能表述为「数据不足」。",
        "news": "新闻情绪是辅助事实，不参与 Trend、Alerts 或 Attention Score；缺失不是 neutral，也不得用于推断价格因果。",
        "trend_display": "；".join(f"{key} = {value}" for key, value in TREND_DISPLAY.items()),
    }


def write_json(path: Path, payload: Mapping[str, Any], *, indent: int = 2) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=indent, default=str)
        fh.write("\n")
    return path


def write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return path
