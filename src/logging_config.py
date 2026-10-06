"""logging 初始化（spec §10：必须有 logging，且单只股票失败不能炸掉整个日报）。

控制台 + 文件双输出。Windows 控制台编码（cp936）下遇到无法编码的字符时降级为 '?' 而不是抛异常。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

DEFAULT_FORMAT = "%(asctime)s %(levelname)-7s %(message)s"
DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"

# yfinance 在 ticker 不存在时会往 root logger 里灌 ERROR 原文（HTTP 404 / Failed download），
# 我们自己的 fetcher 已经用一句 WARNING 说清楚了失败原因，这里把第三方噪声压掉。
THIRD_PARTY_LOGGERS = ("yfinance", "peewee", "urllib3", "curl_cffi", "requests", "charset_normalizer")


def setup_logging(
    *,
    level: str | int = "INFO",
    log_file: Path | None = None,
    fmt: str = DEFAULT_FORMAT,
    datefmt: str = DEFAULT_DATEFMT,
    force: bool = True,
    quiet_third_party: bool = True,
) -> logging.Logger:
    """配置 root logger，返回一个名为 'stock_observer' 的 logger。"""
    _make_console_encoding_safe()

    handlers: list[logging.Handler] = [logging.StreamHandler(stream=sys.stdout)]

    if log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            handlers.append(logging.FileHandler(log_file, encoding="utf-8", mode="a"))
        except OSError:  # 日志文件写不了也不能让主流程挂掉
            handlers[0].emit(
                logging.LogRecord(
                    "stock_observer", logging.WARNING, __file__, 0, "无法写入日志文件 %s，仅输出到控制台",
                    (log_file,), None,
                )
            )

    resolved_level = logging.getLevelName(str(level).upper()) if isinstance(level, str) else level
    if not isinstance(resolved_level, int):
        resolved_level = logging.INFO

    formatter = logging.Formatter(fmt=fmt, datefmt=datefmt)
    root = logging.getLogger()
    if force:
        for handler in list(root.handlers):
            root.removeHandler(handler)
    for handler in handlers:
        handler.setFormatter(formatter)
        root.addHandler(handler)
    root.setLevel(resolved_level)

    if quiet_third_party:
        for name in THIRD_PARTY_LOGGERS:
            logging.getLogger(name).setLevel(logging.CRITICAL)

    return logging.getLogger("stock_observer")


def _make_console_encoding_safe() -> None:
    """避免中文/特殊字符在 Windows 控制台触发 UnicodeEncodeError。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # 保留原编码，只放宽错误处理
        except (AttributeError, ValueError, OSError):
            pass
