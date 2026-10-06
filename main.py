"""Poor Man's Bloomberg / 美股科技股每日监控器 —— 入口。

用法（spec §9 / §12）：
    python main.py
    python main.py --config config.yaml --watchlist watchlist.txt
    python main.py --period 2y --log-level DEBUG

跑完在 outputs/ 里生成三份文件：daily_report.md / analysis_input.json / raw_metrics.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src import __version__
from src.config import DEFAULT_CONFIG_NAME, ConfigError, load_config, load_watchlist
from src.logging_config import setup_logging
from src.pipeline import EXIT_ALL_FAILED, EXIT_OK, run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="获取关注列表里美股的历史行情，计算指标，生成日报（市场监控/数据摘要工具，不是投资顾问）。",
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG_NAME, help="配置文件路径（默认 config.yaml）")
    parser.add_argument("--watchlist", default=None, help="关注列表路径（默认取 config.yaml 里的 watchlist，或 watchlist.txt）")
    parser.add_argument("--output-dir", default=None, help="产出目录（默认取 config.yaml 的 outputs.dir）")
    parser.add_argument("--period", default=None, help="覆盖 yfinance 拉取窗口，例如 1y / 2y / 6mo")
    parser.add_argument("--log-level", default=None, help="日志级别：DEBUG / INFO / WARNING / ERROR")
    parser.add_argument("--version", action="version", version=f"stock-observer {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        settings = load_config(args.config)
        settings = settings.with_overrides(period=args.period, output_dir=args.output_dir)
    except ConfigError as exc:
        print(f"[配置错误] {exc}", file=sys.stderr)
        return 1

    logging_cfg = settings.section("logging")
    logger = setup_logging(
        level=args.log_level or logging_cfg.get("level", "INFO"),
        log_file=settings.log_file,
        fmt=str(logging_cfg.get("format", "%(asctime)s %(levelname)-7s %(message)s")),
        datefmt=str(logging_cfg.get("datefmt", "%Y-%m-%d %H:%M:%S")),
        quiet_third_party=bool(logging_cfg.get("quiet_third_party", True)),
    )

    watchlist_path = Path(args.watchlist) if args.watchlist else settings.watchlist_path
    try:
        watchlist = load_watchlist(watchlist_path, logger)
    except ConfigError as exc:
        logger.error("%s", exc)
        return 1

    if not watchlist:
        logger.error("关注列表是空的：%s（先往里写几个 ticker）", watchlist_path)
        return 1

    try:
        result = run_pipeline(settings, watchlist, logger)
    except Exception as exc:  # 兜底：任何意外都要留下痕迹
        logger.exception("流水线执行失败：%s: %s", type(exc).__name__, exc)
        return 1

    _print_summary(result, watchlist_path)
    return result.exit_code


def _print_summary(result, watchlist_path) -> None:
    print("")
    print(f"=== {result.benchmark} 基准 · 美股科技股每日监控 ===")
    print(f"数据截至 : {result.data_as_of or 'n/a'}")
    print(f"生成时间 : {result.generated_at}")
    print(f"标的     : {len(result.rows)} 只成功 / {len(result.failures)} 只失败（watchlist: {watchlist_path}）")

    if result.failures:
        print("失败标的 : " + ", ".join(f"{ticker}({reason})" for ticker, reason in result.failures.items()))

    if result.rows:
        print("")
        print("关注度前几名：")
        for row in result.rows[:5]:
            score = row.get("attention_score")
            alerts = "、".join(row.get("alerts") or []) or "—"
            print(
                f"  {row['ticker']:<6} score={score if score is not None else 'n/a':<5} "
                f"trend={row.get('trend')} 1D={_pct(row.get('return_1d_pct'))} alerts={alerts}"
            )

    print("")
    print("产出文件：")
    for name, path in result.output_paths.items():
        print(f"  {name:<15} {path}")
    print("")
    print("下一步：把 outputs/daily_report.md（或 analysis_input.json）连同")
    print("        prompts/chatgpt_analysis_prompt.md 里的固定 Prompt 一起丢给 ChatGPT。")
    print("        注意：Attention Score 表达「今天值不值得看一眼」，不是买入评分。")


def _pct(value) -> str:
    return "n/a" if value is None else f"{float(value):+.2f}%"


if __name__ == "__main__":
    raise SystemExit(main())
