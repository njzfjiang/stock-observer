"""行情清洗与可用性校验的回归测试。"""

from __future__ import annotations

import logging

import numpy as np

from src.fetcher import fetch_all


def test_fetch_all_validates_min_rows_after_normalization(make_frame, settings):
    """原始行数够、有效 Close 不够时，不能把清洗后的短数据误判为可用。"""
    raw = make_frame(np.linspace(100.0, 140.0, 40))
    raw.loc[raw.index[:15], "Close"] = np.nan

    def downloader(tickers, _settings, _logger):
        return raw

    local = settings.with_overrides()
    local.raw["history"]["retry_failed_individually"] = False
    frames, failures = fetch_all(["AAPL"], local, logging.getLogger("test_fetcher"), downloader=downloader)

    assert frames == {}
    assert failures == {"AAPL": "insufficient data (25 rows, need >= 30)"}
