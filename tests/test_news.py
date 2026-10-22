"""新闻情绪模块离线测试。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

import pytest

from src.news import NEWS_PARTIAL, NEWS_UNAVAILABLE, fetch_news, normalize_url


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def article(ticker: str, *, url: str = "https://Example.com/story/?utm_source=test", score: str = "0.4"):
    return {
        "title": "Chip demand update",
        "url": url,
        "source": "Example Wire",
        "time_published": "20261022T120000",
        "summary": "Public provider summary.",
        "ticker_sentiment": [
            {
                "ticker": ticker,
                "relevance_score": "0.8",
                "ticker_sentiment_score": score,
                "ticker_sentiment_label": "Bullish" if float(score) > 0 else "Bearish",
            }
        ],
    }


def test_fetch_news_deduplicates_url_and_aggregates_by_ticker(settings):
    payloads = {"AAPL": {"feed": [article("AAPL")]}, "MSFT": {"feed": [article("MSFT", url="https://example.com/story")]}}

    def opener(url, **_kwargs):
        ticker = parse_qs(urlsplit(url).query)["tickers"][0]
        assert "demo-secret" in parse_qs(urlsplit(url).query)["apikey"]
        return FakeResponse(payloads[ticker])

    result = fetch_news(
        ["AAPL", "MSFT"], settings, __import__("logging").getLogger("test"), opener=opener,
        now_utc=datetime(2026, 10, 22, 18, tzinfo=timezone.utc), environ={"ALPHA_VANTAGE_API_KEY": "demo-secret"},
    )

    assert result["status"] == "OK"
    assert len(result["articles"]) == 1
    assert result["articles"][0]["associated_tickers"] == ["AAPL", "MSFT"]
    assert result["ticker_summaries"]["AAPL"]["article_count_24h"] == 1
    assert result["ticker_summaries"]["AAPL"]["sentiment_score_24h"] == pytest.approx(0.4)
    assert result["ticker_summaries"]["MSFT"]["sentiment_label_24h"] == "Bullish"


def test_missing_key_is_fail_safe_without_network(settings):
    called = False

    def opener(*_args, **_kwargs):
        nonlocal called
        called = True

    result = fetch_news(["AAPL"], settings, __import__("logging").getLogger("test"), opener=opener, environ={})
    assert result["status"] == NEWS_UNAVAILABLE
    assert "ALPHA_VANTAGE_API_KEY" in result["reason"]
    assert called is False


def test_rate_limit_stops_remaining_requests(settings):
    calls = []

    def opener(url, **_kwargs):
        ticker = parse_qs(urlsplit(url).query)["tickers"][0]
        calls.append(ticker)
        if ticker == "MSFT":
            return FakeResponse({"Note": "API rate limit reached"})
        return FakeResponse({"feed": [article(ticker)]})

    result = fetch_news(
        ["AAPL", "MSFT", "NVDA"], settings, __import__("logging").getLogger("test"), opener=opener,
        now_utc=datetime(2026, 10, 22, 18, tzinfo=timezone.utc), environ={"ALPHA_VANTAGE_API_KEY": "secret"},
    )
    assert result["status"] == NEWS_PARTIAL
    assert calls == ["AAPL", "MSFT"]
    assert result["ticker_summaries"]["MSFT"]["status"] == NEWS_UNAVAILABLE
    assert result["ticker_summaries"]["NVDA"]["status"] == NEWS_UNAVAILABLE


def test_url_normalization_removes_tracking_and_fragment():
    assert normalize_url("https://EXAMPLE.com/a/?b=2&utm_source=x&a=1#top") == "https://example.com/a?a=1&b=2"


def test_network_error_never_exposes_api_key(settings, caplog):
    secret = "super-secret-key"

    def opener(url, **_kwargs):
        raise RuntimeError(f"failed request: {url}")

    result = fetch_news(
        ["AAPL"], settings, __import__("logging").getLogger("test"), opener=opener,
        environ={"ALPHA_VANTAGE_API_KEY": secret},
    )
    serialized = json.dumps(result)
    assert secret not in serialized
    assert secret not in caplog.text
    assert "[REDACTED]" in serialized
