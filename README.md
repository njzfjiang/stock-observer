# Poor Man's Bloomberg / 美股科技股每日监控器 v0.1

每日获取指定美股的历史行情，用**透明、可复现的规则**算出趋势与异常标签，生成：

* 给爸爸看的日报 `outputs/daily_report.md`
* 给 ChatGPT 读的结构化数据 `outputs/analysis_input.json`
* 给 Excel / debug 的全部原始指标 `outputs/raw_metrics.csv`

> **定位**：市场监控 / 数据摘要工具，**不是**自动交易系统，也**不是**投资顾问。
> 只回答「今天这些股票发生了什么、趋势如何、有没有异常」，不回答「明天买什么」。
> 所有标签只描述当前状态，不构成买入或卖出建议。行情数据来自 Yahoo Finance（经 yfinance），仅供家庭/个人研究使用，不对外分发或转售。

---

## 1. 快速开始

```bash
git clone <repo-url> && cd stock-observer

python -m venv .venv
.venv/Scripts/activate          # Windows（macOS/Linux: source .venv/bin/activate）
pip install -r requirements.txt

# 编辑 watchlist.txt，一行一个 ticker
python main.py
```

跑完 `outputs/` 里会出现三个文件：

```
outputs/
├─ daily_report.md        中文日报（给人类看）
├─ analysis_input.json    结构化输入（给 ChatGPT 读）
└─ raw_metrics.csv        全部原始指标（Excel / debug）
```

再把 `daily_report.md`（或 `analysis_input.json`）连同 `prompts/chatgpt_analysis_prompt.md` 里的固定 Prompt 一起丢给 ChatGPT，得到一份爸爸看得懂的中文分析。

### 命令行参数

```bash
python main.py                          # 用 config.yaml + watchlist.txt
python main.py --period 3y              # 覆盖拉取窗口（默认 2y）
python main.py --watchlist my.txt       # 换一个关注列表
python main.py --output-dir /tmp/out    # 换产出目录
python main.py --log-level DEBUG        # 更啰嗦的日志
python main.py --version
```

退出码：`0` 至少一只成功；`2` 全部失败（仍然会生成一份写明 DATA_UNAVAILABLE 的日报）；`1` 配置/参数错误。

---

## 2. 目录结构

```
stock-observer/
├─ main.py                     入口（CLI）
├─ config.yaml                 所有阈值 / 权重 / 路径（改配置不用改代码）
├─ watchlist.txt               关注列表
├─ requirements.txt            运行依赖
├─ requirements-dev.txt        开发依赖（pytest）
├─ pytest.ini
├─ prompts/
│  └─ chatgpt_analysis_prompt.md   固定 ChatGPT Prompt（spec §8）
├─ src/
│  ├─ config.py                配置 + 关注列表加载/校验
│  ├─ logging_config.py        logging 初始化
│  ├─ fetcher.py               yfinance 抓取（失败 → DATA_UNAVAILABLE）
│  ├─ indicators.py            技术指标（纯 pandas/numpy 手写）
│  ├─ rules.py                 趋势分类 + 异常标签（规则判定，不由 LLM 决定）
│  ├─ scoring.py               Attention Score 0–100 及分数构成
│  ├─ report.py                daily_report.md 生成
│  ├─ outputs.py               JSON / CSV / MD 落盘
│  └─ pipeline.py              串起整条流水线
├─ tests/                      pytest（默认全部离线，不联网）
├─ outputs/                    运行产物
└─ logs/run.log                运行日志
```

---

## 3. 算了什么指标

| 指标 | 口径 |
|---|---|
| Daily / 5D / 20D / 60D Return | 用**复权收盘价 Adj Close** 计算，避免分红/拆股把历史收益算歪 |
| SMA20 / SMA50 / SMA200 | 原始收盘价 Close 的简单移动平均 |
| RSI14 | Wilder 平滑（α=1/14）；价格完全不动时记 50（中性），不是 NaN |
| Volume Ratio | 今日成交量 ÷ **今日之前** 20 个交易日的平均成交量（不含今日，避免自我稀释） |
| Volatility 20D | 最近 20 个交易日日收益率的标准差（日频 + 年化两个口径） |
| Drawdown | 当前 Close 相对最近 252 个交易日最高收盘价的回撤；数据不足自动收缩窗口 |
| Current Drawdown (252D) | 当前复权价相对严格 252 日窗口运行高点的跌幅 |
| Maximum Drawdown (252D) | 严格 252 日窗口内从历史高点到其后低点的最大跌幅 |
| Sharpe Ratio (252D) | 252 个日收益的年化 Sharpe；无风险利率来自配置，零波动时为 null |
| Relative Strength vs QQQ | 个股 20 日收益 − QQQ 20 日收益（百分点） |

三项 Risk Metrics 都使用与收益率相同的复权价格序列。少于 253 个有效价格点时统一输出
`DATA_INSUFFICIENT` / `null`，不会缩短窗口冒充 252D；这些都是 historical metrics，不是 BUY/SELL signal。

**趋势分类**（Python 规则，spec §5）：

```
Strong Uptrend    Close > SMA20 > SMA50 > SMA200
Strong Downtrend  Close < SMA20 < SMA50 < SMA200
Uptrend           Close > SMA20 AND Close > SMA50
Downtrend         Close < SMA20 AND Close < SMA50
Neutral           其余
Insufficient Data SMA20/SMA50 不可用（历史太短）—— 不猜
```

**异常标签**（阈值在 `config.yaml` 的 `thresholds` 段）：

```
HIGH_VOLUME     量比 >= 2.0
LARGE_MOVE      |1D 涨跌幅| >= 4%
OVERBOUGHT      RSI14 >= 70
OVERSOLD        RSI14 <= 30
NEW_20D_HIGH    Close >= 不含今日的前 20 日最高收盘价
NEW_20D_LOW     Close <= 不含今日的前 20 日最低收盘价
```

这些标签**只描述状态**，它们不是 `RSI<30 → BUY` 那种信号。理由：股票市场不接受我们的 unit tests。

**Attention Score（0–100）**：趋势 30 + 20D 动量 20 + 相对基准 20 + 成交量异动 15 + 价格事件 15。
分数表达的是「今天值不值得打开看一眼」，不是预期收益，也**不代表看涨**（强上涨和强下跌都给高分）。
权重在 `config.yaml` 的 `attention_score` 段；日报会逐项列出得分与依据，所以爸爸问「为什么 82」时有证据。

---

## 4. 数据缺失的处理

抓取失败**不会偷偷填数字**。失败的 ticker 会在三个文件里都显式标记：

* `daily_report.md` → `## 四、数据缺失（DATA_UNAVAILABLE）`
* `analysis_input.json` → `data_unavailable: [{ticker, status, reason}]`
* `raw_metrics.csv` → 一行 `status = DATA_UNAVAILABLE`

某一只股票失败（写错 ticker、退市、网络抖动）**不会导致整份日报死亡**：其余股票照常计算，日志里留一条
`WARNING XXXXZZ: no data returned (ticker may be wrong or delisted)`。
批量下载失败的 ticker 会自动单独重试一次（`history.retry_failed_individually`）。

---

## 5. 配置

所有阈值、权重、窗口、路径都在 `config.yaml`。常用的几个：

```yaml
project:
  benchmark: "QQQ"          # 相对强弱的基准
  market_tickers: [SPY, QQQ]  # 日报「市场概况」板块
history:
  period: "2y"              # 给 252 个日收益及休市/缺失留足历史
  min_rows: 30              # 少于这么多行 → DATA_UNAVAILABLE
indicators:
  drawdown_lookback_days: 252
  relative_strength_window: 20
risk:
  window: 252
  annual_risk_free_rate: 0.04  # 年化小数；4% 写 0.04，请按采用的假设调整
thresholds:
  high_volume_ratio: 2.0
  large_move_pct: 4.0
report:
  top_n: 5                  # 「需关注个股」展开几张卡片
attention_score:
  trend: {weight: 30, ...}
  momentum_20d: {weight: 20, full_credit_abs_return_pct: 15.0}
  ...
```

---

## 6. 测试

```bash
pip install -r requirements-dev.txt
python -m pytest            # 56 个测试，全部离线（注入假数据，不联网）
```

覆盖：指标口径 vs pandas/numpy 手算、数据不足时不许出现 NaN、趋势五分类与边界、异常标签的阈值边界
（含 `>=` 与 `<` 的临界值）、Attention Score 各项之和 = 总分、失败 ticker 不影响其他股票、
相对强弱口径、风险指标严格窗口与零波动边界、清洗后最小行数、三份产出文件的存在与结构。

> `pytest.ini` 里设了 `--basetemp=.pytest_tmp`：本机 `%TEMP%` 下的 pytest 临时目录无访问权限，
> 临时文件统一放到项目内的 `.pytest_tmp/`（已 gitignore）。

---

## 7. 已知取舍（v0.1 有意为之）

* 收益率用复权价、SMA/RSI 用原始价 —— 所以日报里的 `Close` 和公开行情页面一致，而 20D/60D 收益是真实总收益。
* 默认 `period=2y`，因为 252 个日收益至少需要 253 个有效价格点；手动缩短 period 可能让 Risk Metrics 显示 `DATA_INSUFFICIENT`。
* 成交量在不同数据商之间有差异（Yahoo vs 其他家），量比只用于**内部一致**的比较。
* `Attention Score` 的权重是拍出来的初版，不是拟合出来的；它是「看一眼的提示」，不是模型。

## 8. 明确不做（v0.1）

实时行情、分钟级、自动下单、券商连接、期权、新闻情绪、财报 NLP、LLM 自动调用、收益预测、
AI 买卖建议、复杂回测、数据库、React Dashboard。

## 9. GitHub Actions + Pages 自动发布

工作流 `.github/workflows/daily-pages.yml` 会：

1. 每周一至周五美东时间 17:23 自动运行，也支持 Actions 页面手动触发；
2. 安装依赖并执行全部离线测试；
3. 获取行情并把本次产物写入临时 `build/run/`；
4. 生成静态仪表板以及 `latest.json`、`daily_report.md`、`raw_metrics.csv`；
5. 通过 GitHub Pages artifact 发布，不把每日产物 commit 回源码分支。

全量行情抓取失败时 `main.py` 返回非零退出码，部署步骤不会执行，因此不会用空报告覆盖上一版站点。
周末不会运行；美股节假日会显示数据源最近一个交易日的 `data_as_of`。

首次使用需要在 GitHub 仓库执行一次设置：

1. 打开 **Settings → Pages**；
2. 在 **Build and deployment → Source** 选择 **GitHub Actions**；
3. 在 **Actions** 页面手动运行一次 **Daily market report**，或等待下一次定时任务。

发布地址通常为 `https://<github-user>.github.io/stock-observer/`。定时工作流只会从 GitHub
仓库的默认分支运行，因此 workflow 文件必须存在于默认分支。
