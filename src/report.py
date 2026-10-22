"""daily_report.md 生成（spec §7）：给人类直接看的那一份。

中文为主，字段名与状态标签保留英文（Trend / Alerts / RSI14），方便和 raw_metrics.csv、
analysis_input.json 以及公开行情页面对照。
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from .rules import TREND_DISPLAY

NA = "n/a"


# ---------------------------------------------------------------------------
# 格式化
# ---------------------------------------------------------------------------


def fmt_num(value: Any, decimals: int = 2) -> str:
    if value is None:
        return NA
    return f"{float(value):,.{decimals}f}"


def fmt_pct(value: Any, decimals: int = 2) -> str:
    """带正负号的百分比，涨跌方向一眼能看出来。"""
    if value is None:
        return NA
    return f"{float(value):+.{decimals}f}%"


def fmt_ratio(value: Any, decimals: int = 2) -> str:
    if value is None:
        return NA
    return f"{float(value):.{decimals}f}x"


def fmt_score(value: Any, decimals: int = 1) -> str:
    if value is None:
        return NA
    return f"{float(value):.{decimals}f}"


def fmt_trend(trend: Any) -> str:
    if not trend:
        return NA
    return TREND_DISPLAY.get(str(trend), str(trend))


def fmt_alerts(alerts: Sequence[str] | None, details: Sequence[str] | None = None) -> str:
    if not alerts:
        return "—"
    if details:
        return "、".join(details)
    return "、".join(str(a) for a in alerts)


def fmt_int(value: Any) -> str:
    if value is None:
        return NA
    return f"{float(value):,.0f}"


def fmt_risk(row: Mapping[str, Any], key: str, decimals: int = 2, *, percent: bool = False) -> str:
    """风险窗口不完整时显式标记，避免把 n/a 误解成 0。"""
    if row.get("risk_status") != "OK":
        return "DATA_INSUFFICIENT"
    value = row.get(key)
    return fmt_pct(value, decimals) if percent else fmt_num(value, decimals)


# ---------------------------------------------------------------------------
# 表格片段
# ---------------------------------------------------------------------------


def _table(headers: Sequence[str], rows: Iterable[Sequence[str]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return lines


def _decimals(settings, key: str, default: int) -> int:
    return int(settings.get("report", "decimals", key, default=default))


def _price_dec(settings) -> int:
    return _decimals(settings, "price", 2)


def _pct_dec(settings) -> int:
    return _decimals(settings, "pct", 2)


def _ratio_dec(settings) -> int:
    return _decimals(settings, "ratio", 2)


def _rsi_dec(settings) -> int:
    return _decimals(settings, "rsi", 1)


def _score_dec(settings) -> int:
    return _decimals(settings, "score", 1)


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------


def build_daily_report(
    *,
    rows: Sequence[Mapping[str, Any]],
    failures: Mapping[str, str],
    settings,
    generated_at: str,
    data_as_of: str | None,
    period: str = "1y",
    interval: str = "1d",
    benchmark: str = "QQQ",
    market_tickers: Sequence[str] = (),
    news: Mapping[str, Any] | None = None,
) -> str:
    """拼出完整的 daily_report.md 文本。"""
    benchmark = str(benchmark).upper()
    market_set = [str(t).upper() for t in market_tickers]
    by_ticker = {str(row.get("ticker", "")).upper(): row for row in rows}

    lines: list[str] = []
    lines.append(f"# 美股科技股每日监控 — {data_as_of or '数据不可用'}")
    lines.append("")
    lines.append(f"- **数据截至**：{data_as_of or NA}（数据源里最近一个交易日的收盘价）")
    lines.append(f"- **生成时间**：{generated_at}")
    lines.append(f"- **数据源**：Yahoo Finance via yfinance（`period={period}`, `interval={interval}`, `auto_adjust=False`）")
    lines.append(f"- **标的**：{len(rows)} 只成功 / {len(failures)} 只失败")
    risk_window = int(settings.get("risk", "window", default=252))
    risk_free_pct = float(settings.get("risk", "annual_risk_free_rate", default=0.0)) * 100.0
    lines.append(f"- **风险参数**：窗口 {risk_window} 个交易日日收益；年化无风险利率 {risk_free_pct:g}%")
    lines.append(
        "- **Attention Score 说明**：分数表达「今天值不值得打开看一眼」（趋势偏离中性、成交量/价格异动），"
        f"满分 100；**不是买入评分**，也不代表看涨或看跌。"
    )
    lines.append("")
    lines.append(
        "> 本报告由 Python 规则引擎确定性生成，只描述**已观测到**的价格与成交量数据；"
        "不预测价格，不给出买卖指令。抓取失败的标的会明确写成 `DATA_UNAVAILABLE`，不会用猜测值补全。"
    )
    lines.append("")

    lines.extend(_market_section(by_ticker, market_set, settings, benchmark))
    lines.extend(_attention_section(rows, settings, market_set, benchmark))
    lines.extend(_all_tickers_section(rows, settings, benchmark))

    lines.extend(_news_section(rows, news or {}, settings))

    # 数据缺失
    lines.append("## 五、数据缺失（DATA_UNAVAILABLE）")
    lines.append("")
    if failures:
        for ticker, reason in failures.items():
            lines.append(f"- `{ticker}`：DATA_UNAVAILABLE — {reason}")
    else:
        lines.append("本次运行全部标的都拿到了数据。")
    lines.append("")

    lines.extend(_definitions_section(settings, benchmark, period, interval))
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# 各板块
# ---------------------------------------------------------------------------


def _metric_row(row: Mapping[str, Any], settings, benchmark: str) -> list[str]:
    return [
        str(row.get("ticker", "")),
        fmt_num(row.get("close"), _price_dec(settings)),
        fmt_pct(row.get("return_1d_pct"), _pct_dec(settings)),
        fmt_pct(row.get("return_5d_pct"), _pct_dec(settings)),
        fmt_pct(row.get("return_20d_pct"), _pct_dec(settings)),
        fmt_pct(row.get("return_60d_pct"), _pct_dec(settings)),
        fmt_trend(row.get("trend")),
        fmt_num(row.get("rsi14"), _rsi_dec(settings)),
        fmt_ratio(row.get("volume_ratio"), _ratio_dec(settings)),
        fmt_pct(row.get("volatility_20d_annualized_pct"), _pct_dec(settings)),
        fmt_pct(row.get("drawdown_from_high_pct"), _pct_dec(settings)),
        _vs_benchmark(row, benchmark, settings),
    ]


def _vs_benchmark(row: Mapping[str, Any], benchmark: str, settings) -> str:
    if str(row.get("ticker", "")).upper() == benchmark:
        return "—（基准自身）"
    key = f"relative_strength_{int(settings.get('indicators', 'relative_strength_window', default=20))}d_vs_{benchmark.lower()}"
    return fmt_pct(row.get(key), _pct_dec(settings))


def _market_section(by_ticker: Mapping[str, Mapping[str, Any]], market_set: Sequence[str], settings, benchmark: str) -> list[str]:
    lines = ["## 一、市场概况（Market）", ""]
    present = [ticker for ticker in market_set if ticker in by_ticker]
    missing = [ticker for ticker in market_set if ticker not in by_ticker]

    if present:
        headers = ["Ticker", "Close", "1D", "5D", "20D", "60D", "Trend", "RSI14", "量比", "20D波动(年化)", "距近期高点", f"vs {benchmark}(20D)"]
        lines.extend(_table(headers, (_metric_row(by_ticker[t], settings, benchmark) for t in present)))
        lines.append("")
        for ticker in present:
            row = by_ticker[ticker]
            alerts_text = fmt_alerts(row.get("alerts"), row.get("alert_details"))
            lines.append(f"- **{ticker}**：{fmt_trend(row.get('trend'))}，1D {fmt_pct(row.get('return_1d_pct'), _pct_dec(settings))}，Alerts: {alerts_text}")
        lines.append("")
    if missing:
        lines.append(f"- 缺失的市场标的：{', '.join('`' + t + '`' for t in missing)}（DATA_UNAVAILABLE）")
        lines.append("")
    return lines


def _attention_section(
    rows: Sequence[Mapping[str, Any]],
    settings,
    market_set: Sequence[str],
    benchmark: str,
) -> list[str]:
    top_n = int(settings.get("report", "top_n", default=5))
    exclude_market = bool(settings.get("report", "exclude_market_tickers_from_attention", default=True))

    candidates = [row for row in rows if not (exclude_market and str(row.get("ticker", "")).upper() in market_set)]
    ranking = sorted(candidates, key=lambda row: (-(row.get("attention_score") or 0.0), str(row.get("ticker", ""))))

    lines = ["## 二、需关注个股（Stocks requiring attention）", ""]
    lines.append(
        f"按 Attention Score 从高到低（共 {len(ranking)} 只非指数标的"
        + ("，指数/ETF 见上一节" if exclude_market else "")
        + "）。分数高只表示**今天值得看一眼**，不代表看涨。"
    )
    lines.append("")

    if not ranking:
        lines.append("没有可排序的标的。")
        lines.append("")
        return lines

    for index, row in enumerate(ranking[: max(0, top_n)], start=1):
        lines.extend(_stock_card(index, row, settings, benchmark))

    rest = ranking[max(0, top_n):]
    if rest:
        lines.append("**其余标的（分数较低，明细见下方速览表）**")
        lines.append("")
        lines.extend(
            _table(
                ["Ticker", "Score", "Trend", "1D", "Alerts"],
                (
                    [
                        str(row.get("ticker", "")),
                        fmt_score(row.get("attention_score"), _score_dec(settings)),
                        fmt_trend(row.get("trend")),
                        fmt_pct(row.get("return_1d_pct"), _pct_dec(settings)),
                        fmt_alerts(row.get("alerts")),
                    ]
                    for row in rest
                ),
            )
        )
        lines.append("")
    return lines


def _stock_card(index: int, row: Mapping[str, Any], settings, benchmark: str) -> list[str]:
    ticker = str(row.get("ticker", ""))
    score = row.get("attention_score")
    score_max = row.get("attention_score_max")
    lines: list[str] = []
    lines.append(f"### {index}. {ticker} — Attention Score: {fmt_score(score, _score_dec(settings))} / {fmt_score(score_max, _score_dec(settings))}")
    lines.append("")
    lines.extend(
        _table(
            ["Close", "1D", "5D", "20D", "60D"],
            [[
                fmt_num(row.get("close"), _price_dec(settings)),
                fmt_pct(row.get("return_1d_pct"), _pct_dec(settings)),
                fmt_pct(row.get("return_5d_pct"), _pct_dec(settings)),
                fmt_pct(row.get("return_20d_pct"), _pct_dec(settings)),
                fmt_pct(row.get("return_60d_pct"), _pct_dec(settings)),
            ]],
        )
    )
    lines.append("")
    lines.extend(
        _table(
            ["Trend", "RSI14", "量比(Vol Ratio)", "20D波动(年化)", "距近期高点"],
            [[
                fmt_trend(row.get("trend")),
                fmt_num(row.get("rsi14"), _rsi_dec(settings)),
                fmt_ratio(row.get("volume_ratio"), _ratio_dec(settings)),
                fmt_pct(row.get("volatility_20d_annualized_pct"), _pct_dec(settings)),
                fmt_pct(row.get("drawdown_from_high_pct"), _pct_dec(settings)),
            ]],
        )
    )
    lines.append("")
    lines.extend(
        _table(
            ["SMA20", "SMA50", "SMA200", f"vs {benchmark} (20D)", "成交量(股)"],
            [[
                fmt_num(row.get("sma20"), _price_dec(settings)),
                fmt_num(row.get("sma50"), _price_dec(settings)),
                fmt_num(row.get("sma200"), _price_dec(settings)),
                _vs_benchmark(row, benchmark, settings),
                fmt_int(row.get("volume")),
            ]],
        )
    )
    lines.append("")
    lines.append(
        f"**Risk (1Y / {int(row.get('risk_window_trading_days') or 252)}D historical metrics)**"
    )
    lines.append("")
    lines.extend(
        _table(
            ["Current Drawdown", "Maximum Drawdown", "Sharpe Ratio", "Status"],
            [[
                fmt_risk(row, "current_drawdown_252d_pct", _pct_dec(settings), percent=True),
                fmt_risk(row, "max_drawdown_252d_pct", _pct_dec(settings), percent=True),
                fmt_risk(row, "sharpe_252d", _ratio_dec(settings)),
                str(row.get("risk_status") or "DATA_INSUFFICIENT"),
            ]],
        )
    )
    lines.append("")
    lines.append(f"**Alerts:** {fmt_alerts(row.get('alerts'), row.get('alert_details'))}")
    lines.append("")

    components = row.get("attention_components") or []
    if components:
        lines.append(f"**分数构成（总分 = 各项之和）**")
        lines.append("")
        lines.extend(
            _table(
                ["分项", "得分", "满分", "依据"],
                (
                    [
                        str(component.get("label", component.get("key", ""))),
                        fmt_score(component.get("points"), _score_dec(settings)),
                        fmt_score(component.get("max_points"), _score_dec(settings)),
                        str(component.get("reason", "")),
                    ]
                    for component in components
                ),
            )
        )
        lines.append("")

    notes = row.get("notes") or []
    if notes:
        lines.append("**数据备注:** " + "；".join(str(note) for note in notes))
        lines.append("")
    return lines


def _all_tickers_section(rows: Sequence[Mapping[str, Any]], settings, benchmark: str) -> list[str]:
    if not bool(settings.get("report", "include_full_table", default=True)):
        return []
    lines = ["## 三、全部标的速览", ""]
    ordered = sorted(rows, key=lambda row: (-(row.get("attention_score") or 0.0), str(row.get("ticker", ""))))
    headers = [
        "#", "Ticker", "Close", "1D", "5D", "20D", "60D", "Trend", "RSI14", "量比",
        "Current DD (252D)", "Max DD (252D)", "Sharpe (252D)", f"vs {benchmark}", "Score", "Alerts",
    ]
    table_rows = []
    for index, row in enumerate(ordered, start=1):
        table_rows.append(
            [
                str(index),
                str(row.get("ticker", "")),
                fmt_num(row.get("close"), _price_dec(settings)),
                fmt_pct(row.get("return_1d_pct"), _pct_dec(settings)),
                fmt_pct(row.get("return_5d_pct"), _pct_dec(settings)),
                fmt_pct(row.get("return_20d_pct"), _pct_dec(settings)),
                fmt_pct(row.get("return_60d_pct"), _pct_dec(settings)),
                fmt_trend(row.get("trend")),
                fmt_num(row.get("rsi14"), _rsi_dec(settings)),
                fmt_ratio(row.get("volume_ratio"), _ratio_dec(settings)),
                fmt_risk(row, "current_drawdown_252d_pct", _pct_dec(settings), percent=True),
                fmt_risk(row, "max_drawdown_252d_pct", _pct_dec(settings), percent=True),
                fmt_risk(row, "sharpe_252d", _ratio_dec(settings)),
                _vs_benchmark(row, benchmark, settings),
                fmt_score(row.get("attention_score"), _score_dec(settings)),
                fmt_alerts(row.get("alerts")),
            ]
        )
    lines.extend(_table(headers, table_rows))
    lines.append("")
    return lines


def _news_section(rows: Sequence[Mapping[str, Any]], news: Mapping[str, Any], settings) -> list[str]:
    lookback = int(news.get("lookback_hours") or settings.get("news", "lookback_hours", default=24))
    lines = ["## 四、新闻与情绪（News / Sentiment）", ""]
    lines.append("新闻情绪仅作辅助信息，不参与 Trend、Alerts 或 Attention Score，也不用于推断价格变动原因。")
    lines.append("")
    status = str(news.get("status") or "NEWS_UNAVAILABLE")
    if status in {"NEWS_UNAVAILABLE", "DISABLED"}:
        reason = str(news.get("reason") or "No sentiment data available.")
        lines.append(f"`{status}` — No sentiment data available. ({reason})")
        lines.append("")
        return lines

    lines.append(f"- **Provider**：{news.get('provider', 'n/a')} · **Lookback**：{lookback}h · **Status**：{status}")
    lines.append("")
    for row in rows:
        ticker = str(row.get("ticker", ""))
        summary = row.get("news") if isinstance(row.get("news"), dict) else {}
        count = int(summary.get("article_count_24h") or 0)
        score = summary.get("sentiment_score_24h")
        label = summary.get("sentiment_label_24h") or "No sentiment data available"
        lines.append(f"### {ticker} — {label}")
        lines.append("")
        lines.append(
            f"Articles: {count} · Sentiment: {fmt_score(score, 3)} · "
            f"Positive/Neutral/Negative: {int(summary.get('positive_count') or 0)}/"
            f"{int(summary.get('neutral_count') or 0)}/{int(summary.get('negative_count') or 0)}"
        )
        lines.append("")
        for article in summary.get("articles") or []:
            ticker_data = (article.get("ticker_sentiment") or {}).get(ticker) or {}
            title = str(article.get("title") or "Untitled").replace("[", "\\[").replace("]", "\\]")
            lines.append(
                f"- [{title}]({article.get('url')}) — {article.get('source') or 'Unknown'}, "
                f"{article.get('published_at') or 'n/a'}; sentiment "
                f"{ticker_data.get('sentiment_label') or 'n/a'} ({fmt_score(ticker_data.get('sentiment_score'), 3)})"
            )
        if not count:
            lines.append("- No sentiment data available.")
        lines.append("")
    return lines


def _definitions_section(settings, benchmark: str, period: str, interval: str) -> list[str]:
    indicator_cfg = settings.section("indicators")
    thresholds = settings.section("thresholds")
    volume_window = int(indicator_cfg.get("volume_window", 20))
    drawdown_lookback = int(indicator_cfg.get("drawdown_lookback_days", 252))
    rs_window = int(indicator_cfg.get("relative_strength_window", 20))
    volatility_window = int(indicator_cfg.get("volatility_window", 20))
    risk_window = int(settings.get("risk", "window", default=252))
    risk_free_pct = float(settings.get("risk", "annual_risk_free_rate", default=0.0)) * 100.0

    lines = ["## 六、指标口径与免责", ""]
    lines.append(f"- **收益率（1D/5D/20D/60D）**：用复权收盘价 Adj Close 计算，避免分红/拆股把历史收益算歪。")
    lines.append(f"- **SMA20/50/200、RSI14、旧版距近期高点、新高新低**：用原始收盘价 Close 计算，和公开行情页面上的数字对得上。")
    lines.append(f"- **RSI14**：Wilder 平滑（α=1/14）；价格完全不动时记 50（中性）。")
    lines.append(f"- **Volume Ratio（量比）**：今日成交量 ÷ 今日之前 {volume_window} 个交易日的平均成交量。")
    lines.append(
        f"- **Volatility 20D**：最近 {volatility_window} 个交易日日收益率的标准差；"
        f"表格里给的是年化值（× √{int(indicator_cfg.get('trading_days_per_year', 252))}）。"
    )
    lines.append(f"- **Drawdown（距近期高点）**：当前 Close 相对最近 {drawdown_lookback} 个交易日最高收盘价的回撤（负数 = 低于高点）。数据不足时自动收缩回看窗口。")
    lines.append(
        f"- **Risk (1Y)**：Current/Maximum Drawdown 与 Sharpe 使用复权价；严格使用 {risk_window} 个日收益，"
        f"年化无风险利率假设 {risk_free_pct:g}%。不足 {risk_window + 1} 个有效价格点时标记 `DATA_INSUFFICIENT`，"
        "不缩短窗口；波动率为 0 时 Sharpe 为 n/a。以上仅为 historical metrics，不映射为 BUY / SELL。"
    )
    lines.append(f"- **Relative Strength**：同期收益 − {benchmark} 同期收益（本报告用 {rs_window} 个交易日）。")
    lines.append(
        "- **异常标签阈值**："
        f"HIGH_VOLUME 量比 ≥ {thresholds.get('high_volume_ratio', 2.0)}；"
        f"LARGE_MOVE |1D| ≥ {thresholds.get('large_move_pct', 4.0)}%；"
        f"OVERBOUGHT RSI14 ≥ {thresholds.get('rsi_overbought', 70)}；"
        f"OVERSOLD RSI14 ≤ {thresholds.get('rsi_oversold', 30)}；"
        "NEW_20D_HIGH / NEW_20D_LOW 对比的是**不含今日**的前 20 个交易日收盘价极值。"
    )
    lines.append("- **趋势分类**：Close 与 SMA20/50/200 的大小关系，由 Python 规则判定（Strong Uptrend / Uptrend / Neutral / Downtrend / Strong Downtrend）。")
    lines.append(
        f"- **Attention Score**：趋势 30 + 20D 动量 20 + 相对基准 20 + 成交量异动 15 + 价格事件 15 = 100，"
        f"权重在 `config.yaml` 的 `attention_score` 段，可改。"
    )
    lines.append(f"- **数据窗口**：`period={period}`, `interval={interval}`（{benchmark} 为相对强弱基准）。")
    lines.append("- **新闻情绪**：按 ticker relevance 与时间衰减加权；无有效新闻时为 null，而不是 neutral。新闻与技术事实分开展示，不作因果判断。")
    lines.append("")
    lines.append("**免责声明**：本工具是市场监控 / 数据摘要工具，不是自动交易系统，也不是投资顾问。所有标签只描述当前状态，不构成任何买入或卖出建议。行情数据来自 Yahoo Finance（经 yfinance），仅供家庭/个人研究使用，不对外分发或转售。")
    lines.append("")
    lines.append("**配套文件**：结构化输入 `outputs/analysis_input.json`（给 AI 读）；全部原始指标 `outputs/raw_metrics.csv`（Excel/debug）。")
    lines.append("")
    lines.append("**给 ChatGPT 的固定 Prompt**：见 `prompts/chatgpt_analysis_prompt.md`。")
    return lines
