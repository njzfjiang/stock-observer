"""行情获取（yfinance）。

铁律（spec §3）：抓取失败**不能偷偷填数字**，必须让调用方看到 DATA_UNAVAILABLE 的原因。
某一只股票拿不到数据，绝不能导致整份日报死亡（spec §10）。

对外接口：
    fetch_all(tickers, settings, logger) -> (frames: dict[str, DataFrame], failures: dict[str, str])
"""

from __future__ import annotations

from typing import Callable, Iterable, Mapping

import pandas as pd

# 需要保留的列（Adj Close 缺了就退回 Close，见 indicators.summarize）
WANTED_COLUMNS = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]


def _import_yfinance():
    """延迟导入：没网/没装 yfinance 时，离线测试仍然能注入自己的 fetch 函数跑完整流水线。"""
    import yfinance as yf  # noqa: PLC0415  (故意延迟导入)

    return yf


def download_raw(tickers: list[str], settings, logger) -> pd.DataFrame | None:
    """调用 yfinance 批量下载。整体失败返回 None（由上层标记所有 ticker 失败）。"""
    history_cfg = settings.section("history")
    period = history_cfg.get("period", "1y")
    interval = history_cfg.get("interval", "1d")
    timeout = history_cfg.get("timeout_seconds")

    yf = _import_yfinance()
    logger.info("Fetching %d tickers (period=%s, interval=%s)", len(tickers), period, interval)
    try:
        return yf.download(
            tickers=list(tickers),
            period=period,
            interval=interval,
            auto_adjust=False,        # 同时保留 Close 与 Adj Close，收益用复权价算
            group_by="ticker",
            progress=False,
            threads=True,
            timeout=timeout,
        )
    except Exception as exc:  # 网络/接口异常：记下来，不抛给用户
        logger.warning("yfinance download failed for %s: %s: %s", ",".join(tickers), type(exc).__name__, exc)
        return None


def extract_ticker(raw: pd.DataFrame | None, ticker: str) -> pd.DataFrame | None:
    """从批量下载结果里取出单个 ticker 的 OHLCV（兼容单 ticker 的扁平列返回）。"""
    if raw is None or not isinstance(raw, pd.DataFrame) or raw.empty:
        return None

    if isinstance(raw.columns, pd.MultiIndex):
        first_level = set(map(str, raw.columns.get_level_values(0)))
        if ticker not in first_level:
            return None
        frame = raw[ticker].copy()
    else:
        frame = raw.copy()  # 只下载了一个 ticker 时 yfinance 返回扁平列

    frame = frame.dropna(how="all")
    if frame.empty:
        return None
    frame.columns = [str(column) for column in frame.columns]
    return frame


def normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """统一成：DatetimeIndex（升序、无时区）+ 数值列 + 只有需要的列。"""
    normalized = frame.copy()
    index = pd.to_datetime(normalized.index, errors="coerce")
    if getattr(index, "tz", None) is not None:
        index = index.tz_localize(None)
    normalized.index = index.normalize() if hasattr(index, "normalize") else index
    normalized = normalized[~normalized.index.isna()]
    normalized = normalized[~normalized.index.duplicated(keep="last")].sort_index()

    kept = [column for column in WANTED_COLUMNS if column in normalized.columns]
    normalized = normalized[kept]
    for column in kept:
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
    return normalized.dropna(subset=["Close"])


def validate_frame(frame: pd.DataFrame | None, min_rows: int) -> tuple[bool, str]:
    """判断一只股票的数据够不够用。返回 (是否可用, 失败原因)。"""
    if frame is None or frame.empty:
        return False, "no data returned (ticker may be wrong or delisted)"
    if "Close" not in frame.columns:
        return False, "no Close column in response"
    if len(frame) < min_rows:
        return False, f"insufficient data ({len(frame)} rows, need >= {min_rows})"
    if pd.isna(frame["Close"].iloc[-1]):
        return False, "latest Close is NaN"
    return True, ""


def fetch_all(
    tickers: Iterable[str],
    settings,
    logger,
    *,
    downloader: Callable[[list[str], object, object], pd.DataFrame | None] | None = None,
) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    """批量获取 + 逐只校验；返回 (成功的数据, 失败原因)。

    downloader 可注入，离线测试时不必联网。
    """
    request_list = [str(ticker).upper() for ticker in tickers]
    history_cfg = settings.section("history")
    min_rows = int(history_cfg.get("min_rows", 30))
    retry_individually = bool(history_cfg.get("retry_failed_individually", True))
    download = downloader or download_raw

    frames: dict[str, pd.DataFrame] = {}
    failures: dict[str, str] = {}
    if not request_list:
        return frames, failures

    raw = download(request_list, settings, logger)
    for ticker in request_list:
        candidate = extract_ticker(raw, ticker)
        candidate = normalize_frame(candidate) if candidate is not None else None
        ok, reason = validate_frame(candidate, min_rows)
        if ok:
            frames[ticker] = candidate
            logger.info("%s OK: %d rows", ticker, len(candidate))
        else:
            failures[ticker] = reason

    if retry_individually and failures:
        logger.info("Retrying %d ticker(s) individually: %s", len(failures), ", ".join(failures))
        for ticker in list(failures):
            single_raw = download([ticker], settings, logger)
            candidate = extract_ticker(single_raw, ticker)
            candidate = normalize_frame(candidate) if candidate is not None else None
            ok, reason = validate_frame(candidate, min_rows)
            if ok:
                frames[ticker] = candidate
                failures.pop(ticker, None)
                logger.info("%s OK after retry: %d rows", ticker, len(candidate))
            else:
                failures[ticker] = reason

    for ticker, reason in failures.items():
        logger.warning("%s: %s", ticker, reason)

    return frames, failures


def frames_from_mapping(data: Mapping[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """把测试/离线用的 {ticker: DataFrame} 走一遍同样的归一化，保证口径一致。"""
    return {str(ticker).upper(): normalize_frame(frame) for ticker, frame in data.items()}
