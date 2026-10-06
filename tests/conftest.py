"""pytest 公共 fixture。

注意：测试用的是项目里真实的 config.yaml —— 顺手保证配置文件本身没被改坏。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.config import load_config

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config.yaml"

USEFUL_COLUMNS = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]


@pytest.fixture(scope="session")
def settings():
    return load_config(CONFIG_PATH)


@pytest.fixture
def make_frame():
    """构造合成 OHLCV。closes 用列表/数组给，adj_close 默认等于 Close。"""

    def _make(
        closes,
        *,
        start: str = "2025-01-01",
        volume=None,
        adj_close=None,
        with_adj_close: bool = True,
    ) -> pd.DataFrame:
        values = np.asarray(closes, dtype="float64")
        index = pd.bdate_range(start=start, periods=len(values))
        volumes = (
            np.asarray(volume, dtype="float64")
            if volume is not None
            else np.full(len(values), 1_000_000.0)
        )
        frame = pd.DataFrame(
            {
                "Open": values,
                "High": values * 1.01,
                "Low": values * 0.99,
                "Close": values,
                "Volume": volumes,
            },
            index=index,
        )
        if with_adj_close:
            adjusted = np.asarray(adj_close, dtype="float64") if adj_close is not None else values.copy()
            frame["Adj Close"] = adjusted
        return frame[USEFUL_COLUMNS] if with_adj_close else frame[["Open", "High", "Low", "Close", "Volume"]]

    return _make


@pytest.fixture
def ramp():
    """前段持平、最后 window+1 个点线性拉动的价格序列（方便手算窗口收益）。"""

    def _ramp(*, window: int, start: float, end: float, total: int = 260, flat: float = 0.0) -> np.ndarray:
        values = np.full(total, flat if flat else start, dtype="float64")
        values[-window - 1 :] = np.linspace(start, end, window + 1)
        return values

    return _ramp
