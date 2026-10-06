"""端到端流水线测试（离线）：注入假的 fetch 函数，完全不联网。

覆盖 spec §12 的验收点：
* outputs/ 稳定出现三个文件
* 某 ticker 故意写错时其他股票仍正常生成
* 相对强弱 = 个股同期收益 − QQQ 同期收益
* 失败标的一律显式 DATA_UNAVAILABLE，不编数字
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from src.pipeline import EXIT_ALL_FAILED, EXIT_OK, run_pipeline

WATCHLIST = ["QQQ", "SPY", "AAPL", "FAST", "BADTICK"]

# 20 个交易日收益：QQQ +10%，FAST +20%，其他 0%
EXPECTED_20D = {"QQQ": 10.0, "SPY": 0.0, "AAPL": 0.0, "FAST": 20.0}


@pytest.fixture
def offline_fetch(make_frame, ramp):
    """按 ticker 返回合成数据；fail 里的 ticker 一律 DATA_UNAVAILABLE。"""

    def _build(fail=("BADTICK",), include_benchmark: bool = True):
        def _fetch(tickers, settings, logger):
            frames, failures = {}, {}
            for raw_ticker in tickers:
                ticker = str(raw_ticker).upper()
                if ticker in fail:
                    failures[ticker] = "no data returned (ticker may be wrong or delisted)"
                    continue
                if ticker == "QQQ" and not include_benchmark:
                    failures[ticker] = "no data returned (ticker may be wrong or delisted)"
                    continue
                if ticker == "QQQ":
                    closes = ramp(window=20, start=100.0, end=110.0)
                elif ticker == "FAST":
                    closes = ramp(window=20, start=100.0, end=120.0)
                else:
                    closes = ramp(window=20, start=100.0, end=100.0)
                frames[ticker] = make_frame(closes)
            return frames, failures

        return _fetch

    return _build


@pytest.fixture
def local_settings(settings, tmp_path):
    """真实 config，但产出目录换到 tmp_path，避免污染项目。"""
    return settings.with_overrides(output_dir=str(tmp_path / "outputs"))


def read_outputs(result):
    report = result.output_paths["daily_report"].read_text(encoding="utf-8")
    payload = json.loads(result.output_paths["analysis_input"].read_text(encoding="utf-8"))
    metrics = pd.read_csv(result.output_paths["raw_metrics"], encoding="utf-8-sig")
    return report, payload, metrics


def test_run_produces_three_files_and_survives_a_bad_ticker(local_settings, offline_fetch, caplog):
    logger = __import__("logging").getLogger("stock_observer")
    result = run_pipeline(local_settings, WATCHLIST, logger, fetch_func=offline_fetch(), now=lambda: "2026-10-05 21:00:00 CST")

    for key in ("daily_report", "analysis_input", "raw_metrics"):
        assert result.output_paths[key].exists(), key
    assert result.exit_code == EXIT_OK
    assert len(result.rows) == 4          # QQQ / SPY / AAPL / FAST
    assert result.failures == {"BADTICK": "no data returned (ticker may be wrong or delisted)"}
    assert result.data_as_of is not None

    report, payload, metrics = read_outputs(result)

    # ---- 日报 ----
    assert "# 美股科技股每日监控" in report
    assert "## 一、市场概况" in report
    assert "## 二、需关注个股" in report
    assert "## 三、全部标的速览" in report
    assert "## 四、数据缺失（DATA_UNAVAILABLE）" in report
    assert "DATA_UNAVAILABLE" in report and "BADTICK" in report
    assert "Attention Score" in report
    assert "分数构成" in report
    assert "Risk (1Y" in report
    assert "Maximum Drawdown" in report
    assert "不是买入评分" in report
    assert "NaN" not in report

    # ---- JSON ----
    assert payload["data_as_of"] == result.data_as_of
    assert payload["benchmark"] == "QQQ"
    assert payload["watchlist_size"] == len(WATCHLIST)
    assert payload["ticker_count_ok"] == 4
    assert payload["ticker_count_failed"] == 1
    assert [entry["ticker"] for entry in payload["data_unavailable"]] == ["BADTICK"]
    assert payload["data_unavailable"][0]["status"] == "DATA_UNAVAILABLE"

    by_ticker = {entry["ticker"]: entry for entry in payload["tickers"]}
    spec_keys = {
        "ticker", "date", "close", "return_1d_pct", "return_20d_pct", "sma20", "sma50", "sma200",
        "rsi14", "volume_ratio", "relative_strength_20d_vs_qqq", "trend", "alerts",
    }
    assert spec_keys.issubset(by_ticker["FAST"].keys())
    assert by_ticker["FAST"]["attention_score"] is not None
    assert by_ticker["FAST"]["attention_score_breakdown"]
    assert by_ticker["FAST"]["trend"] == "STRONG_UPTREND"
    assert by_ticker["FAST"]["risk"] == {
        "status": "OK",
        "window_trading_days": 252,
        "current_drawdown_pct": pytest.approx(0.0),
        "max_drawdown_pct": pytest.approx(0.0),
        "sharpe_ratio": pytest.approx(by_ticker["FAST"]["risk"]["sharpe_ratio"]),
        "risk_free_rate_annual_pct": pytest.approx(4.0),
    }
    assert payload["risk_parameters"] == {
        "window_trading_days": 252,
        "annual_risk_free_rate": pytest.approx(0.04),
        "risk_free_rate_annual_pct": pytest.approx(4.0),
    }

    # ---- 相对强弱：个股 20D − QQQ 20D ----
    assert by_ticker["FAST"]["return_20d_pct"] == pytest.approx(EXPECTED_20D["FAST"])
    assert by_ticker["QQQ"]["return_20d_pct"] == pytest.approx(EXPECTED_20D["QQQ"])
    assert by_ticker["FAST"]["relative_strength_20d_vs_qqq"] == pytest.approx(10.0, abs=1e-6)
    assert by_ticker["AAPL"]["relative_strength_20d_vs_qqq"] == pytest.approx(-10.0, abs=1e-6)
    assert by_ticker["QQQ"]["relative_strength_20d_vs_qqq"] == pytest.approx(0.0, abs=1e-6)

    # 回归测试：关注度评分必须在相对强弱填好之后计算，否则 RS 分项永远是 0 / n/a
    rs_component = next(c for c in by_ticker["FAST"]["attention_score_breakdown"] if c["component"] == "relative_strength")
    assert rs_component["points"] == pytest.approx(20.0)  # |+10%| 达到满分线
    assert "10.0%" in rs_component["evidence"]
    assert by_ticker["QQQ"]["attention_score_breakdown"][2]["points"] == pytest.approx(0.0)  # 基准自身 RS = 0
    assert "vs QQQ n/a" not in report

    # ---- CSV ----
    assert len(metrics) == len(WATCHLIST)          # 失败标的也占一行
    assert {
        "ticker", "status", "close", "rsi14", "attention_score", "alerts", "score_trend",
        "risk_status", "risk_window_trading_days", "risk_free_rate_annual_pct",
        "current_drawdown_252d_pct", "max_drawdown_252d_pct", "sharpe_252d",
    }.issubset(metrics.columns)
    assert metrics.loc[metrics["ticker"] == "BADTICK", "status"].iloc[0] == "DATA_UNAVAILABLE"
    assert metrics.loc[metrics["ticker"] == "BADTICK", "close"].isna().all()
    assert set(metrics.loc[metrics["status"] == "OK", "ticker"]) == {"QQQ", "SPY", "AAPL", "FAST"}
    # Attention Score 排序：CSV 按分数降序
    ok_rows = metrics[metrics["status"] == "OK"]
    assert list(ok_rows["attention_score"]) == sorted(ok_rows["attention_score"], reverse=True)


def test_all_tickers_failing_still_writes_a_report(local_settings, offline_fetch):
    logger = __import__("logging").getLogger("stock_observer")
    result = run_pipeline(
        local_settings,
        ["BAD1", "BAD2"],
        logger,
        fetch_func=offline_fetch(fail=("BAD1", "BAD2")),
    )

    assert result.exit_code == EXIT_ALL_FAILED   # 一只都没成功 → 非 0
    assert result.rows == []
    assert result.data_as_of is None
    report, payload, metrics = read_outputs(result)
    assert "## 四、数据缺失（DATA_UNAVAILABLE）" in report
    assert "BAD1" in report and "BAD2" in report
    assert payload["ticker_count_ok"] == 0
    assert len(payload["data_unavailable"]) == 2
    assert len(metrics) == 2


def test_missing_benchmark_leaves_relative_strength_null_and_explains(local_settings, offline_fetch):
    logger = __import__("logging").getLogger("stock_observer")
    result = run_pipeline(
        local_settings,
        ["AAPL", "QQQ"],
        logger,
        fetch_func=offline_fetch(include_benchmark=False),
    )

    assert "QQQ" in result.failures
    report, payload, _ = read_outputs(result)
    entry = next(item for item in payload["tickers"] if item["ticker"] == "AAPL")
    assert entry["relative_strength_20d_vs_qqq"] is None
    assert any("QQQ" in note for note in entry["notes"])
    assert "n/a" in report


def test_generated_at_is_recorded(local_settings, offline_fetch):
    logger = __import__("logging").getLogger("stock_observer")
    result = run_pipeline(
        local_settings, ["AAPL"], logger, fetch_func=offline_fetch(fail=()), now=lambda: "2026-10-05 21:00:00 CST"
    )
    _, payload, _ = read_outputs(result)
    assert payload["generated_at"] == "2026-10-05 21:00:00 CST"
    assert result.generated_at == "2026-10-05 21:00:00 CST"
