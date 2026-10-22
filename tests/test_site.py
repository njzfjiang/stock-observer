"""GitHub Pages 静态站点构建测试。"""

from __future__ import annotations

import json

import pytest

from src.site import build_site


def test_build_site_copies_downloads_and_escapes_external_values(tmp_path):
    source = tmp_path / "outputs"
    target = tmp_path / "site"
    source.mkdir()
    payload = {
        "generated_at": "2026-10-05 17:23:00 CDT",
        "data_as_of": "2026-10-05",
        "data_source": "fixture",
        "benchmark": "QQQ",
        "market_tickers": ["QQQ"],
        "ticker_count_ok": 2,
        "ticker_count_failed": 0,
        "disclaimer": "not advice",
        "tickers": [
            {"ticker": "QQQ", "close": 100, "return_1d_pct": 1, "risk": {}, "alerts": []},
            {
                "ticker": "<AAPL>",
                "close": 200,
                "return_1d_pct": -2,
                "return_20d_pct": 4,
                "attention_score": 75,
                "risk": {"current_drawdown_pct": -5, "max_drawdown_pct": -10, "sharpe_ratio": 1.2},
                "alerts": ["<script>alert(1)</script>"],
                "news": {
                    "article_count_24h": 1,
                    "sentiment_score_24h": 0.4,
                    "sentiment_label_24h": "Bullish",
                    "positive_count": 1,
                    "neutral_count": 0,
                    "negative_count": 0,
                    "articles": [{"title": "Earnings <update>", "url": "https://example.com/a", "source": "Wire", "published_at": "2026-10-05T12:00:00Z"}],
                },
            },
        ],
        "data_unavailable": [],
    }
    (source / "analysis_input.json").write_text(json.dumps(payload), encoding="utf-8")
    (source / "daily_report.md").write_text("# report\n", encoding="utf-8")
    (source / "raw_metrics.csv").write_text("ticker,close\nQQQ,100\n", encoding="utf-8")

    paths = build_site(source, target)
    page = paths["index"].read_text(encoding="utf-8")

    assert "&lt;AAPL&gt;" in page
    assert "<script>alert(1)</script>" not in page
    assert "latest.json" in page and "daily_report.md" in page and "raw_metrics.csv" in page
    assert "Earnings &lt;update&gt;" in page and "Bullish" in page
    assert json.loads((target / "latest.json").read_text(encoding="utf-8")) == payload
    assert (target / ".nojekyll").exists()


def test_build_site_requires_all_pipeline_outputs(tmp_path):
    with pytest.raises(FileNotFoundError, match="analysis_input.json"):
        build_site(tmp_path / "missing", tmp_path / "site")
