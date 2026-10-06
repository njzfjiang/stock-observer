"""把流水线产物打包成可直接部署到 GitHub Pages 的静态站点。"""

from __future__ import annotations

import argparse
import html
import json
import shutil
from pathlib import Path
from typing import Any, Mapping, Sequence


REQUIRED_FILES = ("analysis_input.json", "daily_report.md", "raw_metrics.csv")


def build_site(input_dir: Path, site_dir: Path) -> dict[str, Path]:
    """读取一次运行的产物，生成无外部依赖的静态站点。"""
    input_dir = Path(input_dir)
    site_dir = Path(site_dir)
    missing = [name for name in REQUIRED_FILES if not (input_dir / name).is_file()]
    if missing:
        raise FileNotFoundError("missing pipeline output(s): " + ", ".join(missing))

    with (input_dir / "analysis_input.json").open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict) or not isinstance(payload.get("tickers"), list):
        raise ValueError("analysis_input.json must contain a tickers list")

    site_dir.mkdir(parents=True, exist_ok=True)
    index_path = site_dir / "index.html"
    index_path.write_text(render_index(payload), encoding="utf-8", newline="\n")
    shutil.copy2(input_dir / "analysis_input.json", site_dir / "latest.json")
    shutil.copy2(input_dir / "daily_report.md", site_dir / "daily_report.md")
    shutil.copy2(input_dir / "raw_metrics.csv", site_dir / "raw_metrics.csv")
    (site_dir / ".nojekyll").write_text("", encoding="utf-8")
    return {
        "index": index_path,
        "latest_json": site_dir / "latest.json",
        "daily_report": site_dir / "daily_report.md",
        "raw_metrics": site_dir / "raw_metrics.csv",
    }


def render_index(payload: Mapping[str, Any]) -> str:
    rows = [row for row in payload.get("tickers", []) if isinstance(row, dict)]
    market_tickers = {str(ticker).upper() for ticker in payload.get("market_tickers", [])}
    market_rows = [row for row in rows if str(row.get("ticker", "")).upper() in market_tickers]
    attention_rows = [row for row in rows if str(row.get("ticker", "")).upper() not in market_tickers]
    attention_rows.sort(key=lambda row: (-(float(row.get("attention_score") or 0)), str(row.get("ticker", ""))))
    unavailable = [item for item in payload.get("data_unavailable", []) if isinstance(item, dict)]

    market_html = "".join(_market_card(row) for row in market_rows) or '<p class="empty">暂无市场基准数据。</p>'
    attention_html = "".join(_attention_card(row, rank) for rank, row in enumerate(attention_rows[:5], 1))
    table_html = "".join(_table_row(row) for row in rows)
    unavailable_html = "".join(
        f"<li><strong>{_e(item.get('ticker'))}</strong>: {_e(item.get('reason'))}</li>" for item in unavailable
    ) or "<li>本次运行没有抓取失败的标的。</li>"

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light dark">
  <title>美股科技股每日监控 · {_e(payload.get('data_as_of') or '数据不可用')}</title>
  <style>
    :root {{ color-scheme: light; --bg:#f3f6fb; --surface:#fff; --text:#172033; --muted:#667085; --line:#e4e9f1; --blue:#3157d5; --green:#087a55; --red:#c43838; --amber:#a25d00; --shadow:0 12px 30px rgba(31,42,68,.08); }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--text); font:15px/1.55 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; }}
    a {{ color:var(--blue); }}
    .wrap {{ width:min(1180px,calc(100% - 32px)); margin:auto; }}
    header {{ padding:54px 0 32px; background:linear-gradient(135deg,#16203a,#273d7d); color:#fff; }}
    header h1 {{ margin:0 0 8px; font-size:clamp(28px,5vw,46px); letter-spacing:-.03em; }}
    header p {{ margin:5px 0; color:#dce5ff; }}
    .links {{ display:flex; flex-wrap:wrap; gap:10px; margin-top:22px; }}
    .links a {{ color:#fff; border:1px solid rgba(255,255,255,.35); border-radius:999px; padding:8px 14px; text-decoration:none; }}
    main {{ padding:28px 0 52px; }}
    h2 {{ margin:34px 0 14px; font-size:22px; }}
    .stats,.cards {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; }}
    .cards {{ grid-template-columns:repeat(2,minmax(0,1fr)); }}
    .stat,.card,.panel {{ background:var(--surface); border:1px solid var(--line); border-radius:16px; box-shadow:var(--shadow); }}
    .stat {{ padding:18px; }} .stat span {{ color:var(--muted); display:block; font-size:13px; }} .stat strong {{ display:block; margin-top:3px; font-size:24px; }}
    .card {{ padding:20px; }} .card-head {{ display:flex; justify-content:space-between; align-items:start; gap:12px; }}
    .ticker {{ font-size:21px; font-weight:750; }} .score {{ background:#eef2ff; color:#2d48a7; border-radius:999px; padding:4px 9px; font-weight:700; }}
    .metrics {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin-top:16px; }}
    .metric span {{ color:var(--muted); display:block; font-size:12px; }} .metric strong {{ font-size:16px; }}
    .alerts {{ color:var(--amber); margin:14px 0 0; font-size:13px; }}
    .positive {{ color:var(--green); }} .negative {{ color:var(--red); }} .neutral {{ color:var(--text); }}
    .panel {{ overflow:hidden; }} .scroll {{ overflow-x:auto; }}
    table {{ width:100%; border-collapse:collapse; min-width:980px; }}
    th,td {{ border-bottom:1px solid var(--line); padding:11px 13px; text-align:right; white-space:nowrap; }}
    th {{ color:var(--muted); background:#f9fafc; font-size:12px; position:sticky; top:0; }} th:first-child,td:first-child {{ text-align:left; }}
    .note {{ color:var(--muted); font-size:13px; }} .empty {{ color:var(--muted); }}
    .failures {{ margin:0; padding:18px 38px; }}
    footer {{ border-top:1px solid var(--line); padding:24px 0 40px; color:var(--muted); font-size:13px; }}
    @media (max-width:850px) {{ .stats {{ grid-template-columns:repeat(2,1fr); }} .cards {{ grid-template-columns:1fr; }} }}
    @media (max-width:520px) {{ .wrap {{ width:min(100% - 20px,1180px); }} .stats {{ grid-template-columns:1fr 1fr; gap:8px; }} .stat {{ padding:14px; }} .metrics {{ grid-template-columns:repeat(2,1fr); }} }}
  </style>
</head>
<body>
  <header><div class="wrap">
    <h1>美股科技股每日监控</h1>
    <p>数据截至 {_e(payload.get('data_as_of') or 'n/a')} · 生成于 {_e(payload.get('generated_at') or 'n/a')}</p>
    <p>透明、可复核的历史行情摘要；不是自动交易系统，也不构成投资建议。</p>
    <nav class="links"><a href="latest.json">latest.json</a><a href="daily_report.md">daily_report.md</a><a href="raw_metrics.csv">raw_metrics.csv</a></nav>
  </div></header>
  <main class="wrap">
    <section class="stats">
      {_stat('成功标的', payload.get('ticker_count_ok'))}
      {_stat('失败标的', payload.get('ticker_count_failed'))}
      {_stat('相对强弱基准', payload.get('benchmark'))}
      {_stat('数据日期', payload.get('data_as_of'))}
    </section>
    <h2>市场概况</h2><section class="cards">{market_html}</section>
    <h2>需关注个股</h2><p class="note">按 Attention Score 排序；高分表示值得查看，不代表看涨。</p><section class="cards">{attention_html}</section>
    <h2>全部标的</h2><section class="panel scroll"><table><thead><tr><th>Ticker</th><th>Close</th><th>1D</th><th>20D</th><th>Trend</th><th>RSI14</th><th>量比</th><th>vs {_e(payload.get('benchmark'))}</th><th>Current DD</th><th>Max DD</th><th>Sharpe</th><th>Score</th></tr></thead><tbody>{table_html}</tbody></table></section>
    <h2>数据缺失</h2><section class="panel"><ul class="failures">{unavailable_html}</ul></section>
  </main>
  <footer><div class="wrap">{_e(payload.get('disclaimer'))}<br>数据源：{_e(payload.get('data_source'))}</div></footer>
</body>
</html>
"""


def _stat(label: str, value: Any) -> str:
    return f'<div class="stat"><span>{_e(label)}</span><strong>{_e(value if value is not None else "n/a")}</strong></div>'


def _market_card(row: Mapping[str, Any]) -> str:
    return _card(row, None)


def _attention_card(row: Mapping[str, Any], rank: int) -> str:
    return _card(row, rank)


def _card(row: Mapping[str, Any], rank: int | None) -> str:
    prefix = f"#{rank} " if rank is not None else ""
    alerts = " · ".join(str(item) for item in (row.get("alerts") or [])) or "无异常标签"
    risk = row.get("risk") if isinstance(row.get("risk"), dict) else {}
    return f"""<article class="card">
      <div class="card-head"><div><div class="ticker">{_e(prefix + str(row.get('ticker', '')))}</div><div class="note">{_e(row.get('trend') or 'n/a')}</div></div><span class="score">Score {_number(row.get('attention_score'), 1)}</span></div>
      <div class="metrics">
        {_metric('Close', _number(row.get('close'), 2))}
        {_metric('1D', _percent(row.get('return_1d_pct')), _tone(row.get('return_1d_pct')))}
        {_metric('20D', _percent(row.get('return_20d_pct')), _tone(row.get('return_20d_pct')))}
        {_metric('vs benchmark', _percent(row.get('relative_strength_20d_vs_qqq')), _tone(row.get('relative_strength_20d_vs_qqq')))}
        {_metric('RSI14', _number(row.get('rsi14'), 1))}
        {_metric('Volume ratio', _number(row.get('volume_ratio'), 2) + 'x')}
        {_metric('Current DD', _percent(risk.get('current_drawdown_pct')), _tone(risk.get('current_drawdown_pct')))}
        {_metric('Sharpe 1Y', _number(risk.get('sharpe_ratio'), 2), _tone(risk.get('sharpe_ratio')))}
      </div><p class="alerts">{_e(alerts)}</p>
    </article>"""


def _metric(label: str, value: str, tone: str = "neutral") -> str:
    return f'<div class="metric"><span>{_e(label)}</span><strong class="{tone}">{_e(value)}</strong></div>'


def _table_row(row: Mapping[str, Any]) -> str:
    risk = row.get("risk") if isinstance(row.get("risk"), dict) else {}
    values = [
        _e(row.get("ticker")),
        _number(row.get("close"), 2),
        _percent(row.get("return_1d_pct")),
        _percent(row.get("return_20d_pct")),
        _e(row.get("trend") or "n/a"),
        _number(row.get("rsi14"), 1),
        _number(row.get("volume_ratio"), 2) + "x",
        _percent(row.get("relative_strength_20d_vs_qqq")),
        _percent(risk.get("current_drawdown_pct")),
        _percent(risk.get("max_drawdown_pct")),
        _number(risk.get("sharpe_ratio"), 2),
        _number(row.get("attention_score"), 1),
    ]
    tones = ["", "", _tone(row.get("return_1d_pct")), _tone(row.get("return_20d_pct")), "", "", "", _tone(row.get("relative_strength_20d_vs_qqq")), _tone(risk.get("current_drawdown_pct")), _tone(risk.get("max_drawdown_pct")), _tone(risk.get("sharpe_ratio")), ""]
    return "<tr>" + "".join(f'<td class="{tone}">{value}</td>' for value, tone in zip(values, tones)) + "</tr>"


def _number(value: Any, decimals: int) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return "n/a"


def _percent(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):+.2f}%"
    except (TypeError, ValueError):
        return "n/a"


def _tone(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "neutral"
    return "positive" if number > 0 else "negative" if number < 0 else "neutral"


def _e(value: Any) -> str:
    return html.escape(str(value if value is not None else "n/a"), quote=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the static GitHub Pages site from pipeline outputs.")
    parser.add_argument("--input-dir", default="outputs")
    parser.add_argument("--site-dir", default="build/site")
    args = parser.parse_args(argv)
    paths = build_site(Path(args.input_dir), Path(args.site_dir))
    print(f"Site generated: {paths['index']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
