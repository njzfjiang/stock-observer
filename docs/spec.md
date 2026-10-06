# 《美股科技股每日监控器》MVP 需求文档 v0.1

**项目代号：** Poor Man's Bloomberg / 父皇科技股观察站  
**项目负责人：** 墨绥绥（对股票一窍不通）  
**受害开发人员：** D老师 / G老师  
**目标用户：** 一位嫌 Moomoo 每月 10 次分析额度太少的父亲

## 1. 项目目标

开发一个轻量 Python 工具，每日获取用户指定美股的历史行情，计算简单、透明、可验证的趋势指标，并生成适合人类阅读以及适合上传给 ChatGPT 的分析文件。

系统定位为：

> **市场监控 / 数据摘要工具，不是自动交易系统，也不是投资顾问。**

第一版只回答：

**“今天这些股票发生了什么、趋势如何、有没有异常？”**

不回答：

**“明天一定涨什么？”、“应该买多少？”、“什么时候梭哈？”**

资本市场已经有足够多人做这种梦，不缺我们家一个。😑

## 2. MVP 用户流程

```text
watchlist.txt
AAPL
MSFT
NVDA
GOOGL
AMZN
META
AVGO
TSLA
QQQ
SPY

       ↓

Python fetch_data.py
       ↓
获取最近约 1 年日线 OHLCV
       ↓
计算技术指标 / 相对表现
       ↓
规则引擎生成状态标签
       ↓
outputs/
 ├─ daily_report.md
 ├─ analysis_input.json
 └─ raw_metrics.csv
       ↓
用户上传 daily_report.md / JSON 给 ChatGPT
       ↓
固定 Prompt：
“请根据提供的数据解释今日走势……”
       ↓
中文日报
```

第一版**不要让 ChatGPT 自己抓行情**。Python 是事实层，ChatGPT 是解释层。这样哪怕模型突然诗兴大发，至少 `NVDA 今日涨跌幅` 这种数字不是它现场创作的。

## 3. 数据源

MVP 使用 [yfinance 项目](https://github.com/ranaroussi/yfinance/blob/main/README.md?utm_source=chatgpt.com) 获取 Yahoo Finance 行情。

`yfinance` 可以批量下载 ticker 数据，非常适合个人研究原型；但它明确说明自己与 Yahoo 无官方关联，并提醒 Yahoo Finance 数据主要供个人用途，因此本项目限定为**家庭/个人研究工具，不公开销售或重新分发行情数据**。[GitHub](https://github.com/ranaroussi/yfinance/blob/main/README.md?utm_source=chatgpt.com)

需要的数据：

| 字段 | 用途 |
|---|---|
| Date | 日期 |
| Open | 开盘价 |
| High | 最高价 |
| Low | 最低价 |
| Close | 收盘价 |
| Volume | 成交量 |
| Adjusted data | 如数据源提供，用于历史收益计算 |

抓取失败不能偷偷填数字。必须显示：

```text
DATA_UNAVAILABLE
```

宁可告诉爸爸“今天没拿到”，也不能让金融版 Claude 梦游补全。

## 4. 第一版计算指标

每只股票计算以下指标即可：

| 指标 | 定义 |
|---|---|
| Daily Return | 1 日涨跌幅 |
| Return 5D | 5 个交易日涨跌幅 |
| Return 20D | 20 个交易日涨跌幅 |
| Return 60D | 60 个交易日涨跌幅 |
| SMA20 | 20 日简单移动平均 |
| SMA50 | 50 日简单移动平均 |
| SMA200 | 200 日简单移动平均 |
| RSI14 | 14 日 RSI |
| Volume Ratio | 今日成交量 / 20 日平均成交量 |
| Volatility 20D | 最近 20 日收益率波动率 |
| Drawdown | 当前价格距离近期高点的回撤 |
| Relative Strength vs QQQ | 同期收益 − QQQ 同期收益 |

暂时**不要**塞 MACD、布林带、随机指标、Ichimoku、月相、黄道十二宫和黄仁勋当天皮衣颜色。

指标多不等于预测力强。

## 5. 趋势分类

趋势判断必须由 Python 的 deterministic rules 完成，而不是 LLM。

建议第一版：

```text
Strong Uptrend
Close > SMA20 > SMA50 > SMA200

Uptrend
Close > SMA20 AND Close > SMA50

Neutral
没有明显满足上涨/下跌条件

Downtrend
Close < SMA20 AND Close < SMA50

Strong Downtrend
Close < SMA20 < SMA50 < SMA200
```

异常标签：

```text
HIGH_VOLUME:
Volume Ratio >= 2.0

LARGE_MOVE:
abs(Daily Return) >= 4%

OVERBOUGHT:
RSI14 >= 70

OVERSOLD:
RSI14 <= 30

NEW_20D_HIGH:
Close >= previous 20-day high

NEW_20D_LOW:
Close <= previous 20-day low
```

这些标签只是**描述状态**，不要写成：

```text
RSI < 30 → BUY
RSI > 70 → SELL
```

否则爸爸很快会问：“它都说超卖了怎么还跌？”

然后小妹抱着电脑：

`QAQ 哥它为什么不遵守if statement`

因为股票市场不接受我们的 unit tests。

## 6. 可选的“关注度评分”

可以提供 `Attention Score 0–100`，但名字不要叫“买入评分”。

评分表达的是：

> **今天值得不值得打开来看一眼。**

而不是预期收益。

例如由趋势强度、相对 QQQ 表现、成交量异常、近期动量和异常波动共同组成。具体权重放在独立 `config.yaml`，以后可以改，不要硬编码散落在代码里。

输出必须同时保留**分数构成**，例如：

```text
NVDA
Attention Score: 82

Trend:             +25
20D Momentum:      +18
Relative Strength: +17
Volume Activity:   +12
Price Event:       +10
```

这样爸爸问“为什么 82”，我们有证据。

而不是：

> AI 感觉它今天气色不错。

## 7. 输出文件

`raw_metrics.csv` 用于 debug/Excel。

`analysis_input.json` 给 AI，保持结构化，例如：

```json
{
  "ticker": "NVDA",
  "date": "YYYY-MM-DD",
  "close": 0,
  "return_1d_pct": 0,
  "return_20d_pct": 0,
  "sma20": 0,
  "sma50": 0,
  "sma200": 0,
  "rsi14": 0,
  "volume_ratio": 0,
  "relative_strength_20d_vs_qqq": 0,
  "trend": "UPTREND",
  "alerts": []
}
```

`daily_report.md` 给人类直接看：

```text
# US Tech Daily Monitor — YYYY-MM-DD

## Market
SPY: ...
QQQ: ...

## Stocks requiring attention

### NVDA
Close:
1D:
20D:
Trend:
RSI:
Volume:
vs QQQ:
Alerts:

### MSFT
...
```

## 8. ChatGPT 分析 Prompt

每次直接上传 `analysis_input.json` 或 `daily_report.md`，附上：

```text
你是一个市场数据解读助手。

只根据我提供的数据进行分析，不自行补充实时价格或未经提供的事实。

任务：
1. 总结今天整体市场和科技股表现。
2. 找出最值得关注的 3–5 只股票。
3. 对每只股票解释：
   - 当前趋势
   - 短中期动量
   - 相对 QQQ 表现
   - 成交量是否异常
   - 主要风险信号
4. 区分“已观察到的数据”和“可能的解释”。
5. 不预测确定的未来价格。
6. 不给出明确买入/卖出指令。
7. 数据不足时明确写“数据不足”。
8. 最后给出一段 5 句话以内的普通人版总结。

输出中文。
```

这个 prompt 的重点不是免责声明文学，而是**禁止模型补数据**。

## 9. 自动化

v0.1 可以先：

```text
python main.py
```

手动运行。

跑通以后 v0.2 再放到 GitHub Actions，每个美股交易日收盘后一段时间执行。GitHub Actions 官方支持 cron 定时，并且现在可以指定 IANA timezone。[GitHub Docs](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax?s=09\&utm_source=chatgpt.com)



## 10. 非功能需求

代码结构尽量简单，Python 3.11+ 即可。核心依赖优先 `pandas + numpy + yfinance`，技术指标能自己用 pandas 写的就先自己写，避免第一版堆一篮子 TA 库。

必须有 logging，例如：

```text
INFO Fetching 12 tickers
INFO AAPL OK: 252 rows
INFO NVDA OK: 252 rows
WARNING XXXX: no data
INFO Report generated: outputs/daily_report.md
```

某一只股票失败不能导致整个日报死亡。

配置和业务逻辑分离：

```text
config.yaml
watchlist.txt
src/
tests/
outputs/
```

## 11. 明确不做

**v0.1 不做**实时行情、分钟级交易、自动下单、券商账号连接、期权分析、新闻情绪、财报 NLP、LLM 自动调用、收益预测、AI 买卖建议、复杂回测、数据库、React Dashboard。


## 12. 验收标准

D老师/G老师交付后，小妹这种“股票一窍不通”的 QA 应该能做到：

```text
git clone
pip install -r requirements.txt
编辑 watchlist.txt
python main.py
```

然后 `outputs/` 里稳定出现三个文件。

随机抽 3 只股票，手工和公开行情页面核对最新收盘价及涨跌方向；指标没有 `NaN` 灾难；某 ticker 故意写错时其他股票仍正常生成；最后把 `analysis_input.json` 扔给 ChatGPT，能得到一份爸爸看得懂的中文分析。

满足这些条件：

**MVP PASS。**

简单流程：
每天收盘后
    ↓
Python 获取行情
    ↓
计算指标 / alerts / score
    ↓
生成
  index.html      ← 给爸爸看
  latest.json     ← 给 ChatGPT 读
  history/*.json  ← 历史数据
    ↓
GitHub Pages 自动发布

---
