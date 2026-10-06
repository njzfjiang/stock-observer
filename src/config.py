"""配置（config.yaml）与关注列表（watchlist.txt）的加载与校验。

设计要点：
* 所有阈值/权重都来自 config.yaml，代码里不写死（spec §6 / §10）。
* 相对路径一律以 config.yaml 所在目录为基准解析，所以从任何 cwd 运行 `python main.py` 都对。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

# 允许的 ticker 形态：字母/数字，可带 . - ^ = （覆盖 BRK.B / ^GSPC / BTC-USD 这类写法）
TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-^=]{0,11}$")

DEFAULT_CONFIG_NAME = "config.yaml"
DEFAULT_WATCHLIST_NAME = "watchlist.txt"


class ConfigError(RuntimeError):
    """配置文件缺失 / 结构不合法。"""


@dataclass
class Settings:
    """已加载的配置。`raw` 是原始 dict，其余是少量常用访问器。"""

    raw: dict[str, Any]
    config_path: Path
    watchlist_path: Path

    # ---------- 基础访问 ----------

    @property
    def project_root(self) -> Path:
        """相对路径的解析基准（= config.yaml 所在目录）。"""
        return self.config_path.parent

    def section(self, name: str) -> dict[str, Any]:
        """取一个配置段落；不存在返回空 dict，类型不对直接报错（早期暴露错配置）。"""
        value = self.raw.get(name)
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ConfigError(f"config.yaml 中 `{name}` 应该是一个映射（dict），实际是 {type(value).__name__}")
        return value

    def get(self, *keys: str, default: Any = None) -> Any:
        """按路径取配置值，例如 settings.get("thresholds", "large_move_pct", default=4.0)。"""
        node: Any = self.raw
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def require(self, *keys: str) -> Any:
        value = self.get(*keys, default=_MISSING)
        if value is _MISSING:
            raise ConfigError(f"config.yaml 缺少必填配置项：{'.'.join(keys)}")
        return value

    # ---------- 常用路径 ----------

    def resolve(self, path_like: str | Path) -> Path:
        """把配置里的相对路径解析成绝对路径（相对 config.yaml 所在目录）。"""
        path = Path(path_like)
        return path if path.is_absolute() else (self.project_root / path)

    @property
    def outputs_dir(self) -> Path:
        return self.resolve(self.get("outputs", "dir", default="outputs"))

    @property
    def log_file(self) -> Path:
        return self.resolve(self.get("logging", "file", default="logs/run.log"))

    def output_path(self, key: str) -> Path:
        """outputs/ 下的某个产物文件。key ∈ {daily_report, analysis_input, raw_metrics}。"""
        filename = self.get("outputs", key)
        if not filename:
            raise ConfigError(f"config.yaml 缺少 outputs.{key}")
        return self.outputs_dir / filename

    def with_overrides(self, *, period: str | None = None, output_dir: str | None = None) -> "Settings":
        """CLI 覆盖少量配置（不改磁盘上的 config.yaml）。"""
        raw = _deep_copy(self.raw)
        if period:
            raw.setdefault("history", {})["period"] = period
        if output_dir:
            raw.setdefault("outputs", {})["dir"] = output_dir
        return Settings(raw=raw, config_path=self.config_path, watchlist_path=self.watchlist_path)


_MISSING = object()


def _deep_copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _deep_copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_deep_copy(v) for v in value]
    return value


def load_config(path: str | Path = DEFAULT_CONFIG_NAME) -> Settings:
    """读取 config.yaml。"""
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"找不到配置文件：{config_path}（请在项目根目录运行 python main.py）")
    with config_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{config_path} 顶层必须是一个映射（dict）")

    config_path = config_path.resolve()
    watchlist_raw = raw.get("watchlist") or DEFAULT_WATCHLIST_NAME
    watchlist_path = Path(watchlist_raw)
    if not watchlist_path.is_absolute():
        watchlist_path = config_path.parent / watchlist_path
    return Settings(raw=raw, config_path=config_path, watchlist_path=watchlist_path)


def parse_watchlist(lines: Iterable[str]) -> tuple[list[str], list[tuple[int, str]]]:
    """解析关注列表文本。

    返回 (tickers, rejected)：tickers 已大写去重并保持原始顺序；rejected 是 (行号, 原文)。
    """
    tickers: list[str] = []
    rejected: list[tuple[int, str]] = []
    seen: set[str] = set()

    for lineno, line in enumerate(lines, start=1):
        text = line.split("#", 1)[0].strip()
        if not text:
            continue
        ticker = text.upper()
        if not TICKER_RE.match(ticker):
            rejected.append((lineno, text))
            continue
        if ticker in seen:
            continue
        seen.add(ticker)
        tickers.append(ticker)
    return tickers, rejected


def load_watchlist(path: str | Path, logger=None) -> list[str]:
    """读取 watchlist.txt，返回去重后的 ticker 列表。格式不对的行跳过并告警。"""
    watchlist_path = Path(path)
    if not watchlist_path.exists():
        raise ConfigError(f"找不到关注列表：{watchlist_path}")
    with watchlist_path.open("r", encoding="utf-8") as fh:
        tickers, rejected = parse_watchlist(fh)

    if logger is not None:
        for lineno, text in rejected:
            logger.warning("watchlist.txt 第 %d 行格式不合法，已跳过：%r", lineno, text)
        logger.info("Loaded watchlist: %d tickers from %s", len(tickers), watchlist_path)
    return tickers
