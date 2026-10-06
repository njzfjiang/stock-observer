
新增需求：Risk Metrics

背景：
用户希望日报除趋势/动量指标外，增加风险指标：

1. Current Drawdown
2. Maximum Drawdown
3. Sharpe Ratio

目标：
用于描述股票过去一段时间的历史风险特征，
不作为 BUY/SELL signal，不参与交易决策。

========================================

1. Current Drawdown (252D)

定义：
当前价格相对于过去 252 个交易日运行最高点的跌幅。

running_peak = price.rolling / cumulative peak
drawdown = price / running_peak - 1

输出：
current_drawdown_252d_pct

示例：
-6.8%

========================================

2. Maximum Drawdown (252D)

定义：
过去 252 个交易日内，从任一历史高点到其后低点
所出现的最大跌幅。

输出：
max_drawdown_252d_pct

示例：
-23.7%

注意：
必须使用与收益率计算一致的价格序列，
避免拆股等 corporate actions 导致虚假回撤。

========================================

3. Sharpe Ratio (252D, annualized)

使用过去 252 个交易日的 daily returns。

daily_return = price.pct_change()

建议计算：

daily_rf = (1 + annual_risk_free_rate) ** (1/252) - 1

excess_daily_return = daily_return - daily_rf

sharpe_252d =
    mean(excess_daily_return)
    / std(excess_daily_return, ddof=1)
    * sqrt(252)

输出：
sharpe_252d

risk-free rate 不要硬编码在计算逻辑中。

config.yaml：

risk:
  window: 252
  annual_risk_free_rate: <configurable></configurable>

报告和 JSON 必须同时记录计算使用的：

- window
- annual_risk_free_rate

如果没有足够数据，输出 null / DATA_INSUFFICIENT，
禁止静默使用更短区间冒充 252D。

如果 volatility == 0，则 Sharpe 输出 null，
避免 division by zero。

========================================

JSON 示例：

"risk": {
  "window_trading_days": 252,
  "current_drawdown_pct": -6.8,
  "max_drawdown_pct": -23.7,
  "sharpe_ratio": 1.24,
  "risk_free_rate_annual_pct": 4.0
}

========================================

展示：

Risk (1Y)
Current Drawdown: -6.8%
Maximum Drawdown: -23.7%
Sharpe Ratio: 1.24

说明：
以上均为 historical metrics。
不得自动映射为 BUY / SELL recommendation。
