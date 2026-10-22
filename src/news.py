"""Alpha Vantage 新闻情绪获取、去重与按 ticker 聚合。

新闻是辅助事实层：失败不得中断行情流水线，也不得参与任何交易/关注度规则。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import urlopen

NEWS_UNAVAILABLE = "NEWS_UNAVAILABLE"
NEWS_OK = "OK"
NEWS_PARTIAL = "PARTIAL"
NEWS_DISABLED = "DISABLED"
API_URL = "https://www.alphavantage.co/query"

OpenUrl = Callable[..., Any]


def fetch_news(
    tickers: Sequence[str],
    settings,
    logger,
    *,
    opener: OpenUrl | None = None,
    now_utc: datetime | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """逐 ticker 获取新闻，并返回可序列化的全局去重结果。"""
    cfg = settings.section("news")
    provider = str(cfg.get("provider", "alpha_vantage"))
    base = _empty_result(provider, int(cfg.get("lookback_hours", 24)))
    if not bool(cfg.get("enabled", False)):
        base.update(status=NEWS_DISABLED, reason="news is disabled")
        return base
    if provider != "alpha_vantage":
        base.update(status=NEWS_UNAVAILABLE, reason=f"unsupported news provider: {provider}")
        logger.warning("News unavailable: unsupported provider %s", provider)
        return base

    env = os.environ if environ is None else environ
    api_key = str(env.get("ALPHA_VANTAGE_API_KEY", "")).strip()
    if not api_key:
        base.update(status=NEWS_UNAVAILABLE, reason="ALPHA_VANTAGE_API_KEY is not configured")
        logger.warning("News unavailable: ALPHA_VANTAGE_API_KEY is not configured")
        return base

    current = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    lookback_hours = int(cfg.get("lookback_hours", 24))
    cutoff = current - timedelta(hours=lookback_hours)
    max_articles = int(cfg.get("max_articles_per_ticker", 5))
    max_tickers = int(cfg.get("max_tickers_per_run", 15))
    timeout = float(cfg.get("timeout_seconds", 15))
    selected = _unique_tickers(tickers)[:max_tickers]
    base["fetched_at"] = current.isoformat().replace("+00:00", "Z")
    base["tickers_requested"] = selected

    article_map: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}
    rate_limited = False
    attempted: list[str] = []
    open_url = opener or urlopen

    for ticker in selected:
        params = {
            "function": "NEWS_SENTIMENT",
            "tickers": ticker,
            "time_from": cutoff.strftime("%Y%m%dT%H%M"),
            "sort": "LATEST",
            "limit": max_articles,
            "apikey": api_key,
        }
        base["requests_attempted"] += 1
        attempted.append(ticker)
        try:
            with open_url(f"{API_URL}?{urlencode(params)}", timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            provider_error = _provider_error(payload)
            if provider_error:
                provider_error = _redact(provider_error, api_key)
                errors[ticker] = provider_error
                if _is_rate_limit(provider_error):
                    rate_limited = True
                    logger.warning("News API rate limit reached at %s; skipping remaining tickers", ticker)
                    break
                logger.warning("%s: news unavailable: %s", ticker, provider_error)
                continue
            feed = payload.get("feed") if isinstance(payload, dict) else None
            for raw in (feed if isinstance(feed, list) else [])[:max_articles]:
                article = _parse_article(raw, ticker, cutoff)
                if article is None:
                    continue
                key = article.pop("_dedupe_key")
                existing = article_map.get(key)
                if existing is None:
                    article_map[key] = article
                else:
                    existing["associated_tickers"] = sorted(
                        set(existing["associated_tickers"]) | set(article["associated_tickers"])
                    )
                    existing["ticker_sentiment"].update(article["ticker_sentiment"])
        except Exception as exc:
            reason = _safe_error(exc, api_key)
            errors[ticker] = reason
            logger.warning("%s: news unavailable: %s", ticker, reason)

    if rate_limited:
        for ticker in selected[len(attempted):]:
            errors[ticker] = "skipped after provider rate limit"
    articles = sorted(article_map.values(), key=lambda item: item.get("published_at") or "", reverse=True)
    summaries = {
        ticker: _summarize_ticker(ticker, articles, current, cfg)
        for ticker in selected
    }
    for ticker, reason in errors.items():
        summaries[ticker]["status"] = NEWS_UNAVAILABLE
        summaries[ticker]["reason"] = reason
    succeeded = sum(1 for ticker in selected if ticker not in errors)
    if succeeded == 0:
        status = NEWS_UNAVAILABLE
    elif errors or rate_limited or len(selected) < len(_unique_tickers(tickers)):
        status = NEWS_PARTIAL
    else:
        status = NEWS_OK
    base.update(
        status=status,
        reason=("rate limit reached; remaining requests skipped" if rate_limited else None),
        articles=articles,
        ticker_summaries=summaries,
        errors=errors,
    )
    logger.info("News: %s, %d unique article(s), %d ticker error(s)", status, len(articles), len(errors))
    return base


def _empty_result(provider: str, lookback_hours: int) -> dict[str, Any]:
    return {
        "status": NEWS_UNAVAILABLE,
        "provider": provider,
        "lookback_hours": lookback_hours,
        "fetched_at": None,
        "reason": None,
        "requests_attempted": 0,
        "tickers_requested": [],
        "articles": [],
        "ticker_summaries": {},
        "errors": {},
    }


def _unique_tickers(tickers: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(str(ticker).upper() for ticker in tickers))


def _provider_error(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return "invalid provider response"
    for key in ("Note", "Information", "Error Message"):
        value = payload.get(key)
        if value:
            return str(value)
    return None


def _is_rate_limit(message: str) -> bool:
    lowered = message.lower()
    return any(text in lowered for text in ("rate limit", "call frequency", "calls per", "api request"))


def _parse_article(raw: Any, requested_ticker: str, cutoff: datetime) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    title = str(raw.get("title") or "").strip()
    url = str(raw.get("url") or "").strip()
    if not title or not url:
        return None
    if urlsplit(url).scheme.lower() not in {"http", "https"}:
        return None
    published = _parse_provider_time(raw.get("time_published"))
    if published is None or published < cutoff:
        return None
    normalized_url = normalize_url(url)
    dedupe_key = normalized_url or "title:" + hashlib.sha256(title.casefold().encode("utf-8")).hexdigest()
    ticker_data = _ticker_sentiment(raw.get("ticker_sentiment"), requested_ticker)
    article_id = hashlib.sha256(dedupe_key.encode("utf-8")).hexdigest()[:16]
    return {
        "_dedupe_key": dedupe_key,
        "id": article_id,
        "title": title,
        "source": str(raw.get("source") or "Unknown"),
        "published_at": published.isoformat().replace("+00:00", "Z"),
        "url": url,
        "summary": str(raw.get("summary") or "").strip() or None,
        "associated_tickers": [requested_ticker],
        "ticker_sentiment": {requested_ticker: ticker_data},
    }


def normalize_url(url: str) -> str:
    """去 fragment、默认端口和常见追踪参数，生成稳定去重键。"""
    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower()
        port = parts.port
        netloc = host if port in (None, 80, 443) else f"{host}:{port}"
        query = urlencode(
            sorted(
                (key, value)
                for key, value in parse_qsl(parts.query, keep_blank_values=True)
                if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid"}
            )
        )
        path = parts.path.rstrip("/") or "/"
        return urlunsplit((parts.scheme.lower(), netloc, path, query, ""))
    except (TypeError, ValueError):
        return ""


def _parse_provider_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    for fmt in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _ticker_sentiment(items: Any, ticker: str) -> dict[str, Any]:
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and str(item.get("ticker", "")).upper() == ticker:
                return {
                    "sentiment_score": _float_or_none(item.get("ticker_sentiment_score")),
                    "sentiment_label": str(item.get("ticker_sentiment_label") or "") or None,
                    "relevance_score": _float_or_none(item.get("relevance_score")),
                }
    return {"sentiment_score": None, "sentiment_label": None, "relevance_score": None}


def _summarize_ticker(ticker: str, articles: Sequence[Mapping[str, Any]], now: datetime, cfg) -> dict[str, Any]:
    relevant = [article for article in articles if ticker in article.get("associated_tickers", [])]
    positive = neutral = negative = 0
    weighted = weight_total = 0.0
    half_life = max(float(cfg.get("recency_half_life_hours", 24)), 0.01)
    article_ids: list[str] = []
    for article in relevant:
        article_ids.append(str(article.get("id")))
        data = (article.get("ticker_sentiment") or {}).get(ticker) or {}
        score = _float_or_none(data.get("sentiment_score"))
        if score is not None:
            if score > 0.15:
                positive += 1
            elif score < -0.15:
                negative += 1
            else:
                neutral += 1
            relevance = _float_or_none(data.get("relevance_score"))
            published = datetime.fromisoformat(str(article["published_at"]).replace("Z", "+00:00"))
            age_hours = max((now - published).total_seconds() / 3600.0, 0.0)
            weight = max(relevance or 0.0, 0.0) * math.pow(0.5, age_hours / half_life)
            if weight > 0:
                weighted += score * weight
                weight_total += weight
    aggregate = weighted / weight_total if weight_total else None
    return {
        "status": NEWS_OK,
        "article_count_24h": len(relevant),
        "positive_count": positive,
        "neutral_count": neutral,
        "negative_count": negative,
        "sentiment_score_24h": round(aggregate, 6) if aggregate is not None else None,
        "sentiment_label_24h": sentiment_label(aggregate),
        "article_ids": article_ids,
    }


def sentiment_label(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= 0.35:
        return "Bullish"
    if score > 0.15:
        return "Somewhat Bullish"
    if score <= -0.35:
        return "Bearish"
    if score < -0.15:
        return "Somewhat Bearish"
    return "Neutral"


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_error(exc: Exception, api_key: str) -> str:
    """异常可能携带完整请求 URL；任何产物或日志都不得包含 API key。"""
    message = _redact(str(exc), api_key)
    return f"{type(exc).__name__}: {message}"


def _redact(message: str, api_key: str) -> str:
    return message.replace(api_key, "[REDACTED]") if api_key else message
