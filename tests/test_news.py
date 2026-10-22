"""新闻情绪模块离线测试。"""

from __future__ import annotations

import io
import json
from copy import deepcopy
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest

from src.config import Settings
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


def marketaux_article(ticker: str, *, url: str = "https://Example.com/story/?utm_source=test", score: float = 0.4):
    return {
        "uuid": "marketaux-story",
        "title": "Chip demand update",
        "url": url,
        "source": "example.com",
        "published_at": "2026-10-22T12:00:00.000000Z",
        "snippet": "Public provider snippet.",
        "entities": [{"symbol": ticker, "match_score": 12.5, "sentiment_score": score}],
    }


def request_url(request):
    assert request.headers["User-agent"] == "stock-observer/0.1.2"
    assert request.headers["Accept"] == "application/json"
    return request.full_url


@pytest.fixture
def alpha_settings(settings):
    raw = deepcopy(settings.raw)
    raw["news"]["provider"] = "alpha_vantage"
    return Settings(raw=raw, config_path=settings.config_path, watchlist_path=settings.watchlist_path)


def test_marketaux_deduplicates_and_aggregates_entity_sentiment(settings):
    payloads = {
        "AAPL": {"data": [marketaux_article("AAPL")]},
        "MSFT": {"data": [marketaux_article("MSFT", url="https://example.com/story")]},
    }

    def opener(url, **_kwargs):
        query = parse_qs(urlsplit(request_url(url)).query)
        ticker = query["symbols"][0]
        assert query["api_token"] == ["marketaux-secret"]
        assert query["filter_entities"] == ["true"]
        assert query["published_after"] == ["2026-10-21T18:00"]
        return FakeResponse(payloads[ticker])

    result = fetch_news(
        ["AAPL", "MSFT"], settings, __import__("logging").getLogger("test"), opener=opener,
        now_utc=datetime(2026, 10, 22, 18, tzinfo=timezone.utc), environ={"MARKETAUX_API_KEY": "marketaux-secret"},
    )

    assert result["provider"] == "marketaux"
    assert result["status"] == "OK"
    assert len(result["articles"]) == 1
    assert result["articles"][0]["associated_tickers"] == ["AAPL", "MSFT"]
    assert result["ticker_summaries"]["AAPL"]["sentiment_score_24h"] == pytest.approx(0.4)
    assert result["ticker_summaries"]["MSFT"]["sentiment_label_24h"] == "Positive"


def test_alpha_vantage_adapter_deduplicates_url_and_aggregates_by_ticker(alpha_settings):
    payloads = {"AAPL": {"feed": [article("AAPL")]}, "MSFT": {"feed": [article("MSFT", url="https://example.com/story")]}}

    def opener(url, **_kwargs):
        actual_url = request_url(url)
        ticker = parse_qs(urlsplit(actual_url).query)["tickers"][0]
        assert "demo-secret" in parse_qs(urlsplit(actual_url).query)["apikey"]
        return FakeResponse(payloads[ticker])

    result = fetch_news(
        ["AAPL", "MSFT"], alpha_settings, __import__("logging").getLogger("test"), opener=opener,
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
    assert "MARKETAUX_API_KEY" in result["reason"]
    assert called is False


def test_marketaux_bad_request_stops_remaining_requests(settings):
    calls = []

    def opener(request, **_kwargs):
        calls.append(request_url(request))
        raise HTTPError(
            request.full_url, 400, "Bad Request", {},
            io.BytesIO(b'{"error":{"message":"published_after has invalid format"}}'),
        )

    result = fetch_news(
        ["AAPL", "MSFT"], settings, __import__("logging").getLogger("test"), opener=opener,
        environ={"MARKETAUX_API_KEY": "secret"},
    )
    assert len(calls) == 1
    assert result["status"] == NEWS_UNAVAILABLE
    assert "published_after has invalid format" in result["errors"]["AAPL"]
    assert result["errors"]["MSFT"] == "skipped after provider error"


def test_alpha_vantage_rate_limit_stops_remaining_requests(alpha_settings):
    calls = []

    def opener(url, **_kwargs):
        ticker = parse_qs(urlsplit(request_url(url)).query)["tickers"][0]
        calls.append(ticker)
        if ticker == "MSFT":
            return FakeResponse({"Note": "API rate limit reached"})
        return FakeResponse({"feed": [article(ticker)]})

    result = fetch_news(
        ["AAPL", "MSFT", "NVDA"], alpha_settings, __import__("logging").getLogger("test"), opener=opener,
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
        raise RuntimeError(f"failed request: {request_url(url)}")

    result = fetch_news(
        ["AAPL"], settings, __import__("logging").getLogger("test"), opener=opener,
        environ={"MARKETAUX_API_KEY": secret},
    )
    serialized = json.dumps(result)
    assert secret not in serialized
    assert secret not in caplog.text
    assert "[REDACTED]" in serialized
