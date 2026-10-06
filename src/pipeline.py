"""流水线：watchlist → 行情 → 指标 → 趋势/标签 → 关注度 → 三份产出文件。

这是唯一编排所有模块的地方；每个环节都可注入，方便离线测试。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import pandas as pd

from . import report as report_module
from .config import Settings
from .fetcher import fetch_all
from .indicators import summarize
from .outputs import (
    build_analysis_input,
    rs_column,
    write_json,
    write_raw_metrics_csv,
    write_text,
)
from .rules import alert_details, classify_trend, detect_alerts
from .scoring import attention_score

FetchFunc = Callable[[Iterable[str], Settings, Any], tuple[dict[str, pd.DataFrame], dict[str, str]]]

EXIT_OK = 0
EXIT_ALL_FAILED = 2


@dataclass
class RunResult:
    """一次运行的全部结果（供 main.py 打印摘要 / 测试断言）。"""

    generated_at: str
    data_as_of: str | None
    rows: list[dict[str, Any]] = field(default_factory=list)
    failures: dict[str, str] = field(default_factory=dict)
    watchlist: list[str] = field(default_factory=list)
    benchmark: str = "QQQ"
    market_tickers: list[str] = field(default_factory=list)
    output_paths: dict[str, Path] = field(default_factory=dict)
    exit_code: int = EXIT_OK


def timestamp_now() -> str:
    """本地时间戳（带时区名），用于「生成时间」。"""
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def run_pipeline(
    settings: Settings,
    watchlist: Sequence[str],
    logger,
    *,
    fetch_func: FetchFunc | None = None,
    now: Callable[[], str] | None = None,
) -> RunResult:
    """跑完整条流水线并落盘三份文件。返回 RunResult。"""
    generated_at = (now or timestamp_now)()
    benchmark = str(settings.get("project", "benchmark", default="QQQ")).upper()
    market_tickers = [str(t).upper() for t in (settings.get("project", "market_tickers") or [])]
    period = str(settings.get("history", "period", default="1y"))
    interval = str(settings.get("history", "interval", default="1d"))
    thresholds = settings.section("thresholds")
    score_cfg = settings.section("attention_score")
    rs_window = int(settings.get("indicators", "relative_strength_window", default=20))
    rs_key = rs_column(settings)

    tickers = [str(t).upper() for t in watchlist]
    fetcher = fetch_func or fetch_all
    frames, failures = fetcher(tickers, settings, logger)

    rows: list[dict[str, Any]] = []
    for ticker in tickers:
        frame = frames.get(ticker)
        if frame is None:
            continue  # 已在 failures 里
        try:
            rows.append(_compute_metrics_row(ticker, frame, settings, thresholds, rs_key, logger))
        except Exception as exc:  # 单只股票的意外不能炸掉整个日报（spec §10）
            logger.error("%s: unexpected error while computing metrics: %s: %s", ticker, type(exc).__name__, exc)
            failures[ticker] = f"indicator computation failed: {type(exc).__name__}: {exc}"

    # 顺序很重要：相对强弱要等基准算完才填，关注度评分又依赖相对强弱。
    _attach_relative_strength(rows, benchmark, rs_key, rs_window, logger)
    for row in rows:
        _apply_attention_score(row, settings, score_cfg, rs_window, benchmark)

    rows.sort(key=lambda row: (-(row.get("attention_score") or 0.0), str(row.get("ticker", ""))))
    data_as_of = _data_as_of(rows)
    if data_as_of is None:
        logger.warning("没有可用数据，生成的日报会标记全部 DATA_UNAVAILABLE")

    # ---- 落盘 ----
    outputs_dir = settings.outputs_dir
    report_path = settings.output_path("daily_report")
    analysis_path = settings.output_path("analysis_input")
    metrics_path = settings.output_path("raw_metrics")

    report_text = report_module.build_daily_report(
        rows=rows,
        failures=failures,
        settings=settings,
        generated_at=generated_at,
        data_as_of=data_as_of,
        period=period,
        interval=interval,
        benchmark=benchmark,
        market_tickers=market_tickers,
    )
    write_text(report_path, report_text)
    logger.info("Report generated: %s", _relative(report_path, outputs_dir.parent))

    payload = build_analysis_input(
        rows=rows,
        failures=failures,
        settings=settings,
        generated_at=generated_at,
        data_as_of=data_as_of,
        benchmark=benchmark,
        market_tickers=market_tickers,
        watchlist_size=len(tickers),
        period=period,
        interval=interval,
    )
    write_json(analysis_path, payload, indent=int(settings.get("outputs", "json_indent", default=2) or 2))
    logger.info("Analysis input written: %s", _relative(analysis_path, outputs_dir.parent))

    write_raw_metrics_csv(metrics_path, rows, failures, settings)
    logger.info("Raw metrics written: %s", _relative(metrics_path, outputs_dir.parent))

    exit_code = EXIT_OK if rows else EXIT_ALL_FAILED
    logger.info(
        "Done: %d ticker(s) OK, %d failed, data as of %s",
        len(rows),
        len(failures),
        data_as_of or "n/a",
    )

    return RunResult(
        generated_at=generated_at,
        data_as_of=data_as_of,
        rows=rows,
        failures=dict(failures),
        watchlist=tickers,
        benchmark=benchmark,
        market_tickers=market_tickers,
        output_paths={"daily_report": report_path, "analysis_input": analysis_path, "raw_metrics": metrics_path},
        exit_code=exit_code,
    )


def _compute_metrics_row(
    ticker: str,
    frame: pd.DataFrame,
    settings: Settings,
    thresholds: Mapping[str, Any],
    rs_key: str,
    logger,
) -> dict[str, Any]:
    """单只股票的第一步：指标 → 趋势 → 标签。相对强弱与评分由后续步骤补齐。"""
    metrics = summarize(frame, settings)
    trend = classify_trend(metrics)
    metrics["trend"] = trend
    alerts = detect_alerts(metrics, thresholds)
    metrics["alerts"] = alerts
    metrics["alert_details"] = alert_details(alerts, metrics)

    metrics["ticker"] = ticker
    metrics["status"] = "OK"
    metrics["status_reason"] = ""
    metrics["attention_score"] = None
    metrics["attention_score_max"] = None
    metrics["attention_components"] = []
    metrics[rs_key] = None  # 相对强弱要等基准算完再填

    if not metrics.get("sma200_available"):
        logger.debug("%s: SMA200 不可用（历史 %s 行）", ticker, metrics.get("history_rows"))
    return metrics


def _apply_attention_score(
    row: dict[str, Any],
    settings: Settings,
    score_cfg: Mapping[str, Any],
    rs_window: int,
    benchmark: str,
) -> None:
    """第二步：算 Attention Score。必须在相对强弱填好之后调用。"""
    scored = attention_score(
        row,
        list(row.get("alerts") or []),
        score_cfg,
        relative_strength_window=rs_window,
        benchmark=benchmark,
        decimals=int(settings.get("report", "decimals", "score", default=1) or 1),
    )
    row["attention_score"] = scored.get("score")
    row["attention_score_max"] = scored.get("max_score")
    row["attention_components"] = scored.get("components") or []


def _attach_relative_strength(
    rows: list[dict[str, Any]],
    benchmark: str,
    rs_key: str,
    rs_window: int,
    logger,
) -> None:
    """相对强弱 = 个股同期收益 − 基准同期收益（spec §4）。基准缺失时留 None 并说明原因。"""
    return_key = f"return_{rs_window}d_pct"
    benchmark_row = next((row for row in rows if str(row.get("ticker", "")).upper() == benchmark), None)
    benchmark_return = benchmark_row.get(return_key) if benchmark_row else None

    for row in rows:
        value = row.get(return_key)
        if value is None or benchmark_return is None:
            row[rs_key] = None
            notes = row.setdefault("notes", [])
            if row.get("ticker") != benchmark and benchmark_return is None:
                reason = f"基准 {benchmark} 数据缺失，无法计算 {rs_window}D 相对强弱"
            else:
                reason = f"{rs_window}D 收益或基准收益不可用，无法计算相对强弱"
            if reason not in notes:
                notes.append(reason)
            continue
        row[rs_key] = round(float(value) - float(benchmark_return), 6)

    if benchmark_return is None:
        logger.warning("Benchmark %s unavailable: relative strength left as null", benchmark)
    else:
        logger.info(
            "Benchmark %s %dD return: %+.2f%%",
            benchmark,
            rs_window,
            float(benchmark_return),
        )


def _data_as_of(rows: Sequence[Mapping[str, Any]]) -> str | None:
    dates = [str(row["date"]) for row in rows if row.get("date")]
    return max(dates) if dates else None


def _relative(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base)).replace("\\", "/")
    except ValueError:
        return str(path)
