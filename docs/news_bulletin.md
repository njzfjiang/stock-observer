
Feature: Daily News & Sentiment

Goal:
为每日股票监控报告增加相关新闻与新闻情绪，
用于解释“今天可能有哪些公开信息值得关注”。

Important:
News sentiment 是辅助信息，不是预测信号。
v0.1.2 不允许 sentiment 自动触发 BUY / SELL。

---

DATA SOURCE

Primary:
Marketaux Finance & Market News

Fallback adapter:
Alpha Vantage NEWS_SENTIMENT（premium key only）

Config:

news:
  enabled: true
  provider: "marketaux"
  lookback_hours: 24
  max_articles_per_ticker: 3
  max_tickers_per_run: 50

API key:
环境变量 MARKETAUX_API_KEY

禁止：

- API key 写入 repo
- API key 输出到 HTML / JSON
- API key commit 到 GitHub

---

FETCH STRATEGY

每日价格/技术指标计算完成后：

1. 获取 watchlist
2. 对每个 ticker 请求最近 24h 新闻
3. 每 ticker 最多保留配置数量（Marketaux free plan 默认 3 条）
4. 去重
5. 保存 metadata + sentiment
6. 生成 ticker-level sentiment summary

如果 API rate limit / network error：
新闻模块失败不得导致行情日报失败。

输出：

NEWS_UNAVAILABLE

而不是整个程序 exit(1)。

---

ARTICLE FIELDS

每篇新闻保存：

ticker
title
source
published_at
url
sentiment_score
sentiment_label
relevance_score (if available)

如果 provider 提供 summary，可以保存其返回的摘要。

不要自行抓取并重新发布完整新闻正文。

---

DEDUPLICATION

同一篇文章可能涉及多个 ticker。

优先按照：

1. canonical URL
2. normalized URL
3. title hash

进行去重。

允许同一 article 关联多个 ticker。

---

AGGREGATION

为每只股票生成：

article_count_24h
positive_count
neutral_count
negative_count
sentiment_score_24h

不要只使用简单文章数量判断情绪。

如果 provider 提供 ticker relevance 或 entity match score，
聚合时优先以它作为相关度权重。

可选：

weight =
    relevance_score
    * recency_decay

sentiment_24h =
    Σ(sentiment_score * weight)
    / Σ(weight)

如果无有效新闻：
sentiment_score_24h = null

禁止把“没有新闻”解释为 neutral。

---

OUTPUT EXAMPLE

NVDA

News Sentiment (24h): Moderately Positive
Articles: 4

1. [Headline]
   Source: ...
   Published: ...
   Sentiment: Positive
2. [Headline]
   ...

Technical:
Trend: UPTREND
RSI14: 63.2
Current Drawdown: -6.8%
Sharpe 1Y: 1.24

News:
Sentiment: +0.xx
News count: 4

---

AI REPORT RULES

ChatGPT 应分别展示：

A. Price / technical facts
B. News / sentiment facts
C. Interpretation

禁止把三者混为因果关系。

例如：

允许：
“股价上涨，同时相关新闻情绪偏正面。”

禁止：
“因为新闻情绪偏正面，所以股价上涨。”

除非提供的数据本身足以支持因果判断。

---

FAIL-SAFE

News API failure:
技术指标报告仍正常生成。

Sentiment missing:
显示 "No sentiment data available."

API rate limit:
WARNING log + skip remaining requests.

任何新闻数据缺失：
禁止 LLM 自行补全。
