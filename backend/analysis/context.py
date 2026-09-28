"""把股票数据装配成喂给模型的上下文。

这是"AI 分析"功能的核心：模型本身不知道任何行情，它的结论质量完全取决于我们
喂进去什么。这里负责把行情、技术指标、价格统计、K 线、公司概况、财务报表、
财报日历与盈利预测、分析师观点、近期新闻聚合成一段结构化文本。

两条设计原则
------------
1. **不猜数据**：拿不到的字段就写"数据缺失"，并在末尾显式列出缺失清单。宁可让
   模型知道"我没给你现金流数据"，也不要让它编一个。
2. **可核对**：``build_context`` 返回的结构化 dict 与最终渲染出的 prompt 一一对应，
   并通过 ``GET /analysis/context`` 暴露出来。用户可以亲眼看到到底喂了什么。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from ..marketdata import yf_client
from ..marketdata.symbols import market_currency
from . import indicators

# 各段在裁剪时的优先级（数字越小越先被砍）
_TRIM_ORDER = ("news", "candles", "financials", "earnings", "analyst", "profile")

_SECTION_LABELS = {
    "quote": "最新行情",
    "indicators": "技术指标",
    "summary": "价格统计",
    "candles": "近期K线",
    "profile": "公司概况",
    "financials": "财务报表",
    "earnings": "财报日历与盈利预测",
    "analyst": "分析师观点",
    "news": "近期新闻",
}


# --------------------------------------------------------------------------
# 数字格式化（中文习惯）
# --------------------------------------------------------------------------

def _fmt_num(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if number != number:  # NaN
        return "—"
    return f"{number:,.{digits}f}"


def _fmt_amount(value: Any, currency: str | None = None) -> str:
    """按中文习惯用 万亿 / 亿 / 万 表示大额数字。"""
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if number != number:
        return "—"
    sign = "-" if number < 0 else ""
    magnitude = abs(number)
    if magnitude >= 1e12:
        text = f"{sign}{magnitude / 1e12:.2f}万亿"
    elif magnitude >= 1e8:
        text = f"{sign}{magnitude / 1e8:.2f}亿"
    elif magnitude >= 1e4:
        text = f"{sign}{magnitude / 1e4:.2f}万"
    else:
        text = f"{number:,.2f}"
    return f"{text}{currency}" if currency else text


def _fmt_pct(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.{digits}f}%"
    except (TypeError, ValueError):
        return "—"


def _fmt_ratio_as_pct(value: Any, digits: int = 2) -> str:
    """把 0.1234 这种比率格式化成 12.34%。"""
    if value is None:
        return "—"
    try:
        return f"{float(value) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return "—"


def _fmt_vol(value: Any) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if number >= 1e8:
        return f"{number / 1e8:.2f}亿股"
    if number >= 1e4:
        return f"{number / 1e4:.2f}万股"
    return f"{number:,.0f}股"


# --------------------------------------------------------------------------
# 各段装配
# --------------------------------------------------------------------------

def _collect_quote(symbol: str, market: str) -> dict | None:
    return yf_client.get_quote(symbol, market)


def _collect_profile(symbol: str, market: str) -> dict | None:
    return yf_client.get_profile(symbol, market)


def _collect_indicators(frame: pd.DataFrame) -> dict | None:
    if frame is None or frame.empty:
        return None
    snapshot = indicators.latest_snapshot(frame)
    if not snapshot or snapshot.get("close") is None:
        return None
    snapshot["signals"] = indicators.derive_signals(snapshot)
    return snapshot


def _collect_summary(frame: pd.DataFrame) -> dict | None:
    if frame is None or frame.empty:
        return None
    summary = indicators.compute_summary(frame)
    return summary or None


def _collect_candles(frame: pd.DataFrame, detail: int = 20) -> dict | None:
    """近期 K 线明细 + 分区间涨跌幅。"""
    if frame is None or frame.empty:
        return None

    tail = frame.tail(detail)
    rows: list[dict] = []
    for index, row in tail.iterrows():
        rows.append(
            {
                "date": str(pd.to_datetime(index).date()),
                "open": _safe_float(row.get("open")),
                "high": _safe_float(row.get("high")),
                "low": _safe_float(row.get("low")),
                "close": _safe_float(row.get("close")),
                "volume": _safe_float(row.get("volume")),
                "pct_change": _safe_float(row.get("pct_change")),
            }
        )

    close = frame["close"].dropna() if "close" in frame.columns else pd.Series(dtype=float)
    windows: dict[str, float | None] = {}
    for label, window in (("5d", 5), ("20d", 20), ("60d", 60), ("120d", 120)):
        if len(close) > window:
            base = close.iloc[-window - 1]
            if base:
                windows[label] = float((close.iloc[-1] / base - 1.0) * 100.0)

    return {"detail": rows, "window_returns": windows, "total_days": int(len(frame))}


def _collect_financials(symbol: str, market: str) -> dict | None:
    return yf_client.get_financials(symbol, market)


def _collect_earnings(symbol: str, market: str) -> dict | None:
    return yf_client.get_earnings(symbol, market)


def _collect_analyst(symbol: str, market: str) -> dict | None:
    return yf_client.get_analyst(symbol, market)


def _collect_news(symbol: str, market: str, limit: int) -> list[dict]:
    return yf_client.get_news(symbol, market, limit=limit)


def _safe_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if result != result else result


# --------------------------------------------------------------------------
# 上下文装配
# --------------------------------------------------------------------------

DEFAULT_INCLUDE = {
    "quote": True,
    "indicators": True,
    "candles": True,
    "financials": True,
    "earnings": True,
    "analyst": True,
    "news": True,
    "profile": True,
}


def build_context(
    symbol: str,
    market: str,
    frame: pd.DataFrame | None = None,
    *,
    include: dict[str, bool] | None = None,
    news_limit: int = 10,
    candle_detail: int = 20,
) -> dict:
    """聚合分析上下文。

    ``frame`` 为带指标列的行情数据帧（由调用方通过 ``storage.cache`` 获取）。
    各段独立采集并容错：某一段失败只会让它进入 ``missing``，不影响其他段。
    """
    include = {**DEFAULT_INCLUDE, **(include or {})}
    currency = market_currency(market)
    sections: dict[str, Any] = {}
    missing: list[str] = []
    errors: dict[str, str] = {}

    def attempt(name: str, collector, *args, **kwargs):
        if not include.get(name, True):
            return
        try:
            value = collector(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            errors[name] = f"{type(exc).__name__}: {exc}"
            missing.append(name)
            return
        if value is None or (isinstance(value, (list, dict)) and len(value) == 0):
            missing.append(name)
            return
        sections[name] = value

    attempt("quote", _collect_quote, symbol, market)
    attempt("indicators", _collect_indicators, frame)
    attempt("summary", _collect_summary, frame)
    attempt("candles", _collect_candles, frame, candle_detail)
    attempt("profile", _collect_profile, symbol, market)
    attempt("financials", _collect_financials, symbol, market)
    attempt("earnings", _collect_earnings, symbol, market)
    attempt("analyst", _collect_analyst, symbol, market)
    attempt("news", _collect_news, symbol, market, news_limit)

    return {
        "symbol": symbol,
        "market": market,
        "currency": currency,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sections": sections,
        "included": sorted(sections.keys()),
        "missing": sorted(set(missing)),
        "errors": errors,
    }


# --------------------------------------------------------------------------
# 渲染为 prompt
# --------------------------------------------------------------------------

def render_context_text(context: dict, *, candle_detail: int = 20) -> str:
    """把上下文渲染成人可读文本。既用于拼 prompt，也用于「上下文预览」。"""
    sections = context.get("sections") or {}
    currency = context.get("currency") or ""
    lines: list[str] = []

    quote = sections.get("quote") or {}
    profile = sections.get("profile") or {}
    name = quote.get("name") or profile.get("name") or context.get("symbol")

    lines.append(f"标的：{name}（{context.get('symbol')}，{context.get('market')} 市场）")
    lines.append(f"数据时间：{context.get('generated_at')}")

    # ---- 最新行情 ----
    if quote:
        lines.append("")
        lines.append("## 最新行情")
        lines.append(f"- 最新价：{_fmt_num(quote.get('price'))} {currency}")
        change = quote.get("change")
        change_pct = quote.get("change_pct")
        if change is not None:
            direction = "上涨" if change >= 0 else "下跌"
            lines.append(f"- 较前收盘：{direction} {_fmt_num(abs(change))}（{_fmt_pct(change_pct)}）")
        lines.append(f"- 前收盘：{_fmt_num(quote.get('previous_close'))}")
        lines.append(
            f"- 今开 / 最高 / 最低：{_fmt_num(quote.get('open'))} / "
            f"{_fmt_num(quote.get('day_high'))} / {_fmt_num(quote.get('day_low'))}"
        )
        lines.append(
            f"- 成交量：{_fmt_vol(quote.get('volume'))}（近三月均量 {_fmt_vol(quote.get('avg_volume'))}）"
        )
        lines.append(f"- 总市值：{_fmt_amount(quote.get('market_cap'), currency)}")
        if quote.get("week52_high") and quote.get("week52_low"):
            lines.append(
                f"- 52周区间：{_fmt_num(quote.get('week52_low'))} ~ "
                f"{_fmt_num(quote.get('week52_high'))}"
                f"（当前处于区间 {_fmt_pct(quote.get('week52_position_pct'), 1)} 分位）"
            )
        if quote.get("ma50") or quote.get("ma200"):
            lines.append(
                f"- 50日 / 200日均线：{_fmt_num(quote.get('ma50'))} / {_fmt_num(quote.get('ma200'))}"
            )

    # ---- 技术指标 ----
    snapshot = sections.get("indicators") or {}
    if snapshot:
        lines.append("")
        lines.append("## 技术指标")
        ma = snapshot.get("ma") or {}
        ma_text = "，".join(
            f"{key.upper()} {_fmt_num(value)}" for key, value in ma.items() if value is not None
        )
        if ma_text:
            lines.append(f"- 均线：{ma_text}")
        if snapshot.get("rsi14") is not None:
            lines.append(f"- RSI(14)：{_fmt_num(snapshot['rsi14'], 1)}")
        macd = snapshot.get("macd") or {}
        if macd.get("dif") is not None:
            lines.append(
                f"- MACD：DIF {_fmt_num(macd.get('dif'), 3)}，DEA {_fmt_num(macd.get('dea'), 3)}，"
                f"柱 {_fmt_num(macd.get('hist'), 3)}"
            )
        boll = snapshot.get("boll") or {}
        if boll.get("mid") is not None:
            lines.append(
                f"- 布林带(20,2)：上轨 {_fmt_num(boll.get('upper'))}，中轨 {_fmt_num(boll.get('mid'))}，"
                f"下轨 {_fmt_num(boll.get('lower'))}，%B {_fmt_num(boll.get('pct_b'), 3)}"
            )
        kdj = snapshot.get("kdj") or {}
        if kdj.get("k") is not None:
            lines.append(
                f"- KDJ：K {_fmt_num(kdj.get('k'), 1)}，D {_fmt_num(kdj.get('d'), 1)}，"
                f"J {_fmt_num(kdj.get('j'), 1)}"
            )
        if snapshot.get("atr14") is not None:
            lines.append(
                f"- ATR(14)：{_fmt_num(snapshot.get('atr14'))}"
                f"（占价格 {_fmt_pct(snapshot.get('atr_pct'))}）"
            )
        if snapshot.get("volume_ratio") is not None:
            lines.append(f"- 量比(5日)：{_fmt_num(snapshot.get('volume_ratio'), 2)}")
        signals = snapshot.get("signals") or []
        if signals:
            lines.append("- 客观形态判读：")
            for signal in signals:
                lines.append(f"  - {signal}")

    # ---- 价格统计 ----
    summary = sections.get("summary") or {}
    if summary:
        lines.append("")
        lines.append(f"## 价格统计（{summary.get('start_date')} ~ {summary.get('end_date')}）")
        lines.append(f"- 交易日数：{summary.get('count')}")
        lines.append(
            f"- 区间涨跌：{_fmt_pct(summary.get('return_pct'))}"
            f"（首 {_fmt_num(summary.get('first_close'))} → 末 {_fmt_num(summary.get('last_close'))}）"
        )
        lines.append(
            f"- 区间最高 / 最低：{_fmt_num(summary.get('high'))} / {_fmt_num(summary.get('low'))}"
        )
        lines.append(f"- 最大回撤：{_fmt_pct(summary.get('max_drawdown_pct'))}")
        lines.append(
            f"- 日收益波动率：{_fmt_pct(summary.get('volatility_pct'))}"
            f"（年化 {_fmt_pct(summary.get('annualized_volatility_pct'))}）"
        )
        lines.append(
            f"- 单日最大涨幅 / 跌幅：{_fmt_pct(summary.get('max_single_day_gain_pct'))} / "
            f"{_fmt_pct(summary.get('max_single_day_loss_pct'))}"
        )
        lines.append(
            f"- 上涨 / 下跌天数：{summary.get('up_days')} / {summary.get('down_days')}"
        )
        if summary.get("recent_20d_return_pct") is not None:
            lines.append(
                f"- 近20日收益 {_fmt_pct(summary.get('recent_20d_return_pct'))}，"
                f"前20日收益 {_fmt_pct(summary.get('prior_20d_return_pct'))}，"
                f"动能变化 {_fmt_pct(summary.get('momentum_acceleration_pct'))}"
            )

    # ---- 近期 K 线 ----
    candles = sections.get("candles") or {}
    if candles.get("detail"):
        lines.append("")
        lines.append(f"## 近期K线（最近 {len(candles['detail'])} 个交易日，共 {candles.get('total_days')} 日）")
        lines.append("日期 | 开 | 高 | 低 | 收 | 涨跌幅 | 成交量")
        for row in candles["detail"][-candle_detail:]:
            lines.append(
                f"{row['date']} | {_fmt_num(row['open'])} | {_fmt_num(row['high'])} | "
                f"{_fmt_num(row['low'])} | {_fmt_num(row['close'])} | "
                f"{_fmt_pct(row['pct_change'])} | {_fmt_vol(row['volume'])}"
            )
        window_returns = candles.get("window_returns") or {}
        if window_returns:
            parts = [f"{key} {_fmt_pct(value)}" for key, value in window_returns.items()]
            lines.append(f"- 分区间涨跌：{'，'.join(parts)}")

    # ---- 公司概况 ----
    if profile:
        lines.append("")
        lines.append("## 公司概况")
        lines.append(
            f"- 所属：{profile.get('sector') or '—'} / {profile.get('industry') or '—'}"
            f"（{profile.get('country') or '—'}）"
        )
        if profile.get("employees"):
            lines.append(f"- 员工人数：{profile['employees']:,}")
        valuation = [
            ("总市值", _fmt_amount(profile.get("market_cap"), currency)),
            ("市盈率TTM", _fmt_num(profile.get("pe_trailing"))),
            ("预期市盈率", _fmt_num(profile.get("pe_forward"))),
            ("市净率", _fmt_num(profile.get("pb"))),
            ("市销率", _fmt_num(profile.get("ps"))),
            ("EV/EBITDA", _fmt_num(profile.get("ev_to_ebitda"))),
            ("PEG", _fmt_num(profile.get("peg_ratio"))),
        ]
        lines.append("- 估值：" + "，".join(f"{k} {v}" for k, v in valuation))
        profitability = [
            ("毛利率", _fmt_ratio_as_pct(profile.get("gross_margin"))),
            ("营业利润率", _fmt_ratio_as_pct(profile.get("operating_margin"))),
            ("净利率", _fmt_ratio_as_pct(profile.get("profit_margin"))),
            ("ROE", _fmt_ratio_as_pct(profile.get("roe"))),
            ("ROA", _fmt_ratio_as_pct(profile.get("roa"))),
        ]
        lines.append("- 盈利能力：" + "，".join(f"{k} {v}" for k, v in profitability))
        growth = [
            ("营收增速", _fmt_ratio_as_pct(profile.get("revenue_growth"))),
            ("盈利增速", _fmt_ratio_as_pct(profile.get("earnings_growth"))),
        ]
        lines.append("- 成长性：" + "，".join(f"{k} {v}" for k, v in growth))
        health = [
            ("资产负债率(总负债/权益)", _fmt_num(profile.get("debt_to_equity"))),
            ("流动比率", _fmt_num(profile.get("current_ratio"))),
            ("速动比率", _fmt_num(profile.get("quick_ratio"))),
            ("自由现金流", _fmt_amount(profile.get("free_cashflow"), currency)),
        ]
        lines.append("- 财务健康：" + "，".join(f"{k} {v}" for k, v in health))
        lines.append(
            f"- 股息率：{_fmt_num(profile.get('dividend_yield'))}%"
            f"（每股分红 {_fmt_num(profile.get('dividend_rate'))}，派息率 "
            f"{_fmt_ratio_as_pct(profile.get('payout_ratio'))}）"
        )
        lines.append(f"- Beta：{_fmt_num(profile.get('beta'))}")
        if profile.get("summary"):
            lines.append(f"- 业务简介：{profile['summary']}")

    # ---- 财务报表 ----
    financials = sections.get("financials") or {}
    if financials:
        lines.append("")
        lines.append("## 财务报表关键项")
        annual = financials.get("annual") or {}
        for period in sorted(annual.keys(), reverse=True)[:3]:
            row = annual[period]
            lines.append(f"### 年报 {period}")
            lines.append(
                f"- 营收 {_fmt_amount(row.get('revenue'), currency)}"
                f"（同比 {_fmt_ratio_as_pct(row.get('revenue_yoy'))}），"
                f"毛利 {_fmt_amount(row.get('gross_profit'), currency)}"
                f"（毛利率 {_fmt_ratio_as_pct(row.get('gross_margin'))}）"
            )
            lines.append(
                f"- 营业利润 {_fmt_amount(row.get('operating_income'), currency)}"
                f"（营业利润率 {_fmt_ratio_as_pct(row.get('operating_margin'))}），"
                f"净利润 {_fmt_amount(row.get('net_income'), currency)}"
                f"（净利率 {_fmt_ratio_as_pct(row.get('net_margin'))}，"
                f"同比 {_fmt_ratio_as_pct(row.get('net_income_yoy'))}）"
            )
            lines.append(
                f"- 摊薄EPS {_fmt_num(row.get('diluted_eps'))}，"
                f"ROE {_fmt_ratio_as_pct(row.get('roe'))}，ROA {_fmt_ratio_as_pct(row.get('roa'))}"
            )
            lines.append(
                f"- 总资产 {_fmt_amount(row.get('total_assets'), currency)}，"
                f"总负债 {_fmt_amount(row.get('total_liabilities'), currency)}，"
                f"股东权益 {_fmt_amount(row.get('equity'), currency)}"
            )
            lines.append(
                f"- 经营现金流 {_fmt_amount(row.get('operating_cash_flow'), currency)}，"
                f"自由现金流 {_fmt_amount(row.get('free_cash_flow'), currency)}"
                f"（FCF利润率 {_fmt_ratio_as_pct(row.get('fcf_margin'))}），"
                f"资本开支 {_fmt_amount(row.get('capex'), currency)}"
            )
            if row.get("buyback") is not None or row.get("dividends_paid") is not None:
                lines.append(
                    f"- 股东回报：回购 {_fmt_amount(row.get('buyback'), currency)}，"
                    f"分红 {_fmt_amount(row.get('dividends_paid'), currency)}"
                )

        quarterly = financials.get("quarterly") or {}
        recent_quarters = sorted(quarterly.keys(), reverse=True)[:4]
        if recent_quarters:
            lines.append("### 最近季度（单季）")
            lines.append("报告期 | 营收 | 同比 | 净利润 | 同比 | 净利率")
            for period in recent_quarters:
                row = quarterly[period]
                lines.append(
                    f"{period} | {_fmt_amount(row.get('revenue'), currency)} | "
                    f"{_fmt_ratio_as_pct(row.get('revenue_yoy'))} | "
                    f"{_fmt_amount(row.get('net_income'), currency)} | "
                    f"{_fmt_ratio_as_pct(row.get('net_income_yoy'))} | "
                    f"{_fmt_ratio_as_pct(row.get('net_margin'))}"
                )

    # ---- 财报日历与盈利预测 ----
    earnings = sections.get("earnings") or {}
    if earnings:
        lines.append("")
        lines.append("## 财报日历与盈利预测")
        if earnings.get("next_earnings_date"):
            lines.append(f"- 下次财报日：{earnings['next_earnings_date']}")
        if earnings.get("earnings_average") is not None:
            lines.append(
                f"- 本次市场预期 EPS：均值 {_fmt_num(earnings.get('earnings_average'))}"
                f"（区间 {_fmt_num(earnings.get('earnings_low'))} ~ "
                f"{_fmt_num(earnings.get('earnings_high'))}）"
            )
        if earnings.get("revenue_average") is not None:
            lines.append(f"- 本次市场预期营收：{_fmt_amount(earnings.get('revenue_average'), currency)}")

        events = earnings.get("events") or []
        if events:
            lines.append("- 历史 EPS（估值 / 实际 / 意外幅度）：")
            for event in events[:6]:
                lines.append(
                    f"  - {event['date']}：{_fmt_num(event.get('eps_estimate'))} / "
                    f"{_fmt_num(event.get('eps_actual'))} / {_fmt_pct(event.get('surprise_pct'))}"
                )

        eps_estimate = earnings.get("eps_estimate") or {}
        if eps_estimate:
            lines.append("- 未来 EPS 预测：")
            labels = {"0q": "本季", "+1q": "下季", "0y": "本年度", "+1y": "下一年度"}
            for period, row in eps_estimate.items():
                lines.append(
                    f"  - {labels.get(period, period)}：均值 {_fmt_num(row.get('avg'))}，"
                    f"同比 {_fmt_ratio_as_pct(row.get('growth'))}，"
                    f"覆盖分析师 {row.get('analysts') or '—'} 人"
                )

        revenue_estimate = earnings.get("revenue_estimate") or {}
        if revenue_estimate:
            lines.append("- 未来营收预测：")
            for period, row in revenue_estimate.items():
                lines.append(
                    f"  - {labels.get(period, period)}：均值 "
                    f"{_fmt_amount(row.get('avg'), currency)}，"
                    f"同比 {_fmt_ratio_as_pct(row.get('growth'))}"
                )

        revisions = earnings.get("eps_revisions") or {}
        if revisions:
            lines.append("- 近30日 EPS 修正（上调 / 下调家数）：")
            for period, row in revisions.items():
                lines.append(
                    f"  - {labels.get(period, period)}：上调 {row.get('up_30d') or 0} 家，"
                    f"下调 {row.get('down_30d') or 0} 家"
                )

    # ---- 分析师观点 ----
    analyst = sections.get("analyst") or {}
    if analyst:
        lines.append("")
        lines.append("## 分析师观点")
        if analyst.get("target_mean") is not None:
            current = analyst.get("target_current")
            upside = None
            if current:
                upside = (analyst["target_mean"] / current - 1.0) * 100.0
            lines.append(
                f"- 目标价：均值 {_fmt_num(analyst.get('target_mean'))}，"
                f"中位 {_fmt_num(analyst.get('target_median'))}，"
                f"区间 {_fmt_num(analyst.get('target_low'))} ~ "
                f"{_fmt_num(analyst.get('target_high'))}"
                + (f"（相对现价 {_fmt_pct(upside)}）" if upside is not None else "")
            )
        if analyst.get("recommendation_key"):
            lines.append(
                f"- 综合评级：{analyst.get('recommendation_key')}"
                f"（评分 {_fmt_num(analyst.get('recommendation_mean'))}，"
                f"覆盖 {analyst.get('analyst_count') or '—'} 位分析师）"
            )
        recommendations = analyst.get("recommendations") or []
        if recommendations:
            latest = recommendations[0]
            lines.append(
                f"- 评级分布（{latest.get('period')}）：强烈买入 {latest.get('strong_buy') or 0}，"
                f"买入 {latest.get('buy') or 0}，持有 {latest.get('hold') or 0}，"
                f"卖出 {latest.get('sell') or 0}，强烈卖出 {latest.get('strong_sell') or 0}"
            )
        holders = analyst.get("holders") or {}
        if holders:
            lines.append(
                f"- 持股结构：内部人 {_fmt_ratio_as_pct(holders.get('insidersPercentHeld'))}，"
                f"机构 {_fmt_ratio_as_pct(holders.get('institutionsPercentHeld'))}"
            )

    # ---- 近期新闻 ----
    news = sections.get("news") or []
    if news:
        lines.append("")
        lines.append(f"## 近期新闻（{len(news)} 条）")
        for index, item in enumerate(news, 1):
            published = (item.get("published_at") or "")[:16].replace("T", " ")
            publisher = item.get("publisher") or "未知来源"
            lines.append(f"{index}. [{published}] {item.get('title')}（{publisher}）")
            if item.get("summary"):
                lines.append(f"   摘要：{item['summary']}")

    return "\n".join(lines)


def build_system_prompt(language: str = "zh") -> str:
    if language == "en":
        return (
            "You are a rigorous equity research assistant. You analyse ONLY the data "
            "provided by the user; you never invent prices, financials or news. "
            "When a data point is missing, you say so explicitly. "
            "You never give buy/sell instructions and you always close with a disclaimer."
        )
    return (
        "你是一位严谨的股票研究助理。你**只依据用户提供的数据**进行分析，"
        "绝不编造价格、财务数字或新闻；数据缺失时明确说明「该数据未提供」，"
        "不做推测性填补。你不给出买卖指令，不使用「必涨」「稳赚」这类绝对化措辞，"
        "并在结尾附上免责声明。"
    )


def build_question_prompt(
    context: dict,
    *,
    question: str | None = None,
    language: str = "zh",
    focus: list[str] | None = None,
) -> str:
    """把上下文 + 用户问题组装成最终的用户消息。"""
    body = render_context_text(context)

    if language == "en":
        header = (
            "Below is the VERIFIED market data for the target. "
            "Analyse it and answer in English.\n\n"
        )
        requirements = (
            "\n\n## Output requirements\n"
            "Structure your answer with these headings:\n"
            "1. **Snapshot** – what the company is, current price action and valuation level.\n"
            "2. **Trend & Momentum** – moving-average structure, RSI/MACD/KDJ readings, volume behaviour.\n"
            "3. **Fundamentals** – revenue/profit trend, margins, cash flow, balance-sheet health.\n"
            "4. **Earnings & Expectations** – recent EPS surprises, forward estimates, analyst targets.\n"
            "5. **News & Catalysts** – what the recent headlines imply, and their limits.\n"
            "6. **Risks** – at least three concrete risks drawn from the data above.\n"
            "7. **Disclaimer** – one sentence stating this is not investment advice.\n\n"
            "Cite the specific numbers you rely on. Do not invent any figure that is "
            "not in the data above."
        )
    else:
        header = "以下是该标的的**已核实**市场数据。请基于它进行分析。\n\n"
        requirements = (
            "\n\n## 输出要求\n"
            "请按以下小标题组织回答：\n"
            "1. **标的全貌**：公司做什么、当前价格位置与估值水平。\n"
            "2. **趋势与动能**：均线结构、RSI/MACD/KDJ 读数、量能变化。\n"
            "3. **基本面**：营收与利润趋势、利润率、现金流、资产负债健康度。\n"
            "4. **财报与预期**：近期 EPS 是否超预期、未来预测、分析师目标价。\n"
            "5. **新闻与催化**：近期新闻说明了什么，以及它们的局限。\n"
            "6. **风险点**：至少列出三条**基于上述数据**的具体风险。\n"
            "7. **免责声明**：一句话说明不构成投资建议。\n\n"
            "引用你依据的具体数字。不要编造上述数据中没有的任何数值。"
        )

    focus_block = ""
    if focus:
        labels_zh = {
            "technical": "技术面",
            "fundamental": "基本面",
            "news": "消息面",
            "valuation": "估值",
            "risk": "风险",
        }
        labels_en = {
            "technical": "technical",
            "fundamental": "fundamental",
            "news": "news",
            "valuation": "valuation",
            "risk": "risk",
        }
        mapping = labels_en if language == "en" else labels_zh
        picked = [mapping.get(item, item) for item in focus]
        if picked:
            focus_block = (
                f"\n\n## Analysis focus\nPrioritise: {', '.join(picked)}.\n"
                if language == "en"
                else f"\n\n## 侧重方向\n请重点分析：{'、'.join(picked)}。\n"
            )

    missing = context.get("missing") or []
    if missing:
        labels = [_SECTION_LABELS.get(item, item) for item in missing]
        if language == "en":
            missing_block = (
                f"\n\n## Missing data\n"
                f"The following sections could NOT be retrieved: {', '.join(labels)}. "
                "Explicitly state which parts of your analysis are limited by this."
            )
        else:
            missing_block = (
                f"\n\n## 数据缺失说明\n"
                f"以下数据**未能获取**：{'、'.join(labels)}。"
                "请在回答中明确指出哪些结论因此受限。"
            )
    else:
        missing_block = ""

    question_block = ""
    if question and question.strip():
        label = "User question" if language == "en" else "用户问题"
        question_block = f"\n\n## {label}\n{question.strip()}"

    return f"{header}{body}{focus_block}{question_block}{missing_block}{requirements}"


# --------------------------------------------------------------------------
# 预算裁剪
# --------------------------------------------------------------------------

def fit_budget(context: dict, max_chars: int, *, candle_detail: int = 20) -> tuple[dict, list[str]]:
    """按字符预算裁剪上下文。

    返回 ``(裁剪后的上下文, 被裁剪的说明列表)``。裁剪按 ``_TRIM_ORDER`` 的顺序
    依次收缩新闻条数、K 线根数、财报期数，最后才考虑整段丢弃。
    """
    trimmed: list[str] = []
    working = {
        **context,
        "sections": {k: v for k, v in (context.get("sections") or {}).items()},
    }

    def size() -> int:
        return len(render_context_text(working, candle_detail=candle_detail))

    if size() <= max_chars:
        return working, trimmed

    sections = working["sections"]

    # 1) 新闻：先砍到 5 条，再砍到 3 条
    for limit in (5, 3):
        if size() <= max_chars:
            break
        news = sections.get("news")
        if isinstance(news, list) and len(news) > limit:
            sections["news"] = news[:limit]
            trimmed.append(f"新闻裁剪至 {limit} 条")

    # 2) K 线：20 → 10 → 5 根
    for limit in (10, 5):
        if size() <= max_chars:
            break
        candles = sections.get("candles")
        if isinstance(candles, dict) and len(candles.get("detail") or []) > limit:
            candles = dict(candles)
            candles["detail"] = candles["detail"][-limit:]
            sections["candles"] = candles
            trimmed.append(f"K线裁剪至 {limit} 根")

    # 3) 财报：年报 3 期 → 2 期 → 1 期；季度明细整体去掉
    for limit in (2, 1):
        if size() <= max_chars:
            break
        financials = sections.get("financials")
        if isinstance(financials, dict):
            annual = financials.get("annual") or {}
            if len(annual) > limit:
                financials = dict(financials)
                keep = sorted(annual.keys(), reverse=True)[:limit]
                financials["annual"] = {k: annual[k] for k in keep}
                financials.pop("quarterly", None)
                sections["financials"] = financials
                trimmed.append(f"财报裁剪至 {limit} 期年报（季度明细已省略）")

    if size() <= max_chars:
        return working, trimmed

    # 4) 整段丢弃（按优先级从低到高）
    for name in _TRIM_ORDER:
        if size() <= max_chars:
            break
        if name in sections:
            sections.pop(name, None)
            trimmed.append(f"因超出长度预算，已移除「{_SECTION_LABELS.get(name, name)}」")
            working["missing"] = sorted(set(working.get("missing") or []) | {name})

    return working, trimmed
