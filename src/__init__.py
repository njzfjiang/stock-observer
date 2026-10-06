"""Stock Observer —— 美股科技股每日监控器（市场监控 / 数据摘要工具）。

模块划分：
    config           配置与关注列表加载
    logging_config   logging 初始化
    fetcher          yfinance 行情获取（失败返回 DATA_UNAVAILABLE，绝不填数字）
    indicators       技术指标计算（纯 pandas/numpy，不依赖 TA 库）
    rules            趋势分类 + 异常标签（deterministic rules，不由 LLM 决定）
    scoring          Attention Score 0-100 及分数构成
    report           daily_report.md 生成
    outputs          analysis_input.json / raw_metrics.csv / daily_report.md 落盘
    pipeline         串起整条流水线

定位声明：本工具是市场监控 / 数据摘要工具，不是自动交易系统，也不是投资顾问。
"""

__version__ = "0.1.0"
