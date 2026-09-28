"""yfinance 数据访问层。

统一封装报价、公司概况、财务报表、盈利预测、分析师观点与新闻，并对上层提供
**永远不抛异常**的接口：拿不到就返回 ``None`` 或空集合，让调用方自己决定如何降级。
行情接口在境外源上偶尔抽风是常态，一个字段缺失不应该让整个页面 500。

同时带一层 TTL 内存缓存 —— ``Ticker.info`` 单次调用可能要 1~3 秒，而它在报价、
概况、财务里都要用，不缓存会让一次查询慢到不可接受。
"""

from __future__ import annotations

import math
import threading
import time
from typing import Any, Callable

import pandas as pd
import yfinance as yf

from .symbols import market_currency, to_yf_symbol

# --------------------------------------------------------------------------
# TTL 缓存
# --------------------------------------------------------------------------

_QUOTE_TTL = 60.0
_INFO_TTL = 900.0
_STATEMENT_TTL = 3600.0
_NEWS_TTL = 600.0
_EARNINGS_TTL = 1800.0

_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()


def _cached(key: str, ttl: float, factory: Callable[[], Any]) -> Any:
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None and now - hit[0] < ttl:
            return hit[1]
    value = factory()
    with _cache_lock:
        _cache[key] = (now, value)
        if len(_cache) > 512:
            stale = [k for k, (ts, _) in _cache.items() if now - ts > 3600]
            for k in stale:
                _cache.pop(k, None)
    return value


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


# --------------------------------------------------------------------------
# 通用取值工具
# --------------------------------------------------------------------------

def _get(obj: Any, key: str, default: Any = None) -> Any:
    """兼容 dict 风格与属性风格（yfinance 不同版本返回类型不一致）。"""
    if obj is None:
        return default
    value = None
    if hasattr(obj, "get"):
        try:
            value = obj.get(key)
        except Exception:  # noqa: BLE001
            value = None
    if value is None:
        value = getattr(obj, key, None)
    return default if value is None else value


def _num(value: Any) -> float | None:
    """转成有限浮点数；``"N/A"``、NaN、Inf 一律返回 None。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def _int(value: Any) -> int | None:
    result = _num(value)
    return None if result is None else int(result)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in ("n/a", "nan", "none", "-"):
        return None
    return text


def _date_str(value: Any) -> str | None:
    if value is None:
        return None
    try:
        stamp = pd.to_datetime(value, errors="coerce")
        if stamp is None or pd.isna(stamp):
            return None
        return str(stamp.date())
    except Exception:  # noqa: BLE001
        return None


def _ticker(symbol: str, market: str) -> yf.Ticker:
    return yf.Ticker(to_yf_symbol(symbol, market))


def _info(ticker: yf.Ticker, symbol: str, market: str) -> dict:
    """带缓存的 ``Ticker.info``。失败返回空 dict。"""

    def load() -> dict:
        try:
            data = ticker.info
            return data if isinstance(data, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    return _cached(f"info:{market}:{symbol}", _INFO_TTL, load) or {}


# --------------------------------------------------------------------------
# 报价
# --------------------------------------------------------------------------

def get_quote(symbol: str, market: str) -> dict | None:
    """实时（或最近收盘）报价快照。"""

    def load() -> dict | None:
        ticker = _ticker(symbol, market)
        try:
            fast = ticker.fast_info
        except Exception:  # noqa: BLE001
            fast = None

        info = _info(ticker, symbol, market)

        price = _num(_get(fast, "lastPrice"))
        if price is None:
            price = _num(info.get("currentPrice")) or _num(info.get("regularMarketPrice"))
        if price is None:
            # 兜底：拉最近两根日线自己算
            try:
                history = ticker.history(period="5d", interval="1d")
                if not history.empty:
                    price = _num(history["Close"].iloc[-1])
            except Exception:  # noqa: BLE001
                pass
        if price is None:
            return None

        prev_close = _num(_get(fast, "previousClose")) or _num(
            info.get("regularMarketPreviousClose")
        ) or _num(info.get("previousClose"))

        change = None
        change_pct = None
        if prev_close:
            change = price - prev_close
            change_pct = change / prev_close * 100.0

        year_high = _num(_get(fast, "yearHigh")) or _num(info.get("fiftyTwoWeekHigh"))
        year_low = _num(_get(fast, "yearLow")) or _num(info.get("fiftyTwoWeekLow"))

        return {
            "symbol": symbol,
            "market": market,
            "name": _text(info.get("shortName")) or _text(info.get("longName")),
            "long_name": _text(info.get("longName")),
            "price": price,
            "previous_close": prev_close,
            "change": change,
            "change_pct": change_pct,
            "open": _num(_get(fast, "open")) or _num(info.get("open")),
            "day_high": _num(_get(fast, "dayHigh")) or _num(info.get("dayHigh")),
            "day_low": _num(_get(fast, "dayLow")) or _num(info.get("dayLow")),
            "volume": _int(_get(fast, "lastVolume")) or _int(info.get("volume")),
            "avg_volume": _int(_get(fast, "threeMonthAverageVolume")),
            "market_cap": _num(_get(fast, "marketCap")) or _num(info.get("marketCap")),
            "currency": _text(_get(fast, "currency"))
            or _text(info.get("currency"))
            or market_currency(market),
            "exchange": _text(_get(fast, "exchange")) or _text(info.get("exchange")),
            "quote_type": _text(_get(fast, "quoteType")) or _text(info.get("quoteType")),
            "week52_high": year_high,
            "week52_low": year_low,
            "week52_position_pct": (
                (price - year_low) / (year_high - year_low) * 100.0
                if (year_high and year_low and year_high > year_low)
                else None
            ),
            "ma50": _num(_get(fast, "fiftyDayAverage")) or _num(info.get("fiftyDayAverage")),
            "ma200": _num(_get(fast, "twoHundredDayAverage"))
            or _num(info.get("twoHundredDayAverage")),
            "timezone": _text(_get(fast, "timezone")),
        }

    return _cached(f"quote:{market}:{symbol}", _QUOTE_TTL, load)


# --------------------------------------------------------------------------
# 公司概况
# --------------------------------------------------------------------------

def get_profile(symbol: str, market: str) -> dict | None:
    """公司概况与估值指标。"""

    def load() -> dict | None:
        ticker = _ticker(symbol, market)
        info = _info(ticker, symbol, market)
        if not info:
            return None

        summary = _text(info.get("longBusinessSummary"))
        if summary and len(summary) > 1200:
            summary = summary[:1200] + "…"

        return {
            "symbol": symbol,
            "market": market,
            "name": _text(info.get("shortName")) or _text(info.get("longName")),
            "long_name": _text(info.get("longName")),
            "sector": _text(info.get("sector")),
            "industry": _text(info.get("industry")),
            "country": _text(info.get("country")),
            "website": _text(info.get("website")),
            "employees": _int(info.get("fullTimeEmployees")),
            "summary": summary,
            # 估值
            "market_cap": _num(info.get("marketCap")),
            "enterprise_value": _num(info.get("enterpriseValue")),
            "pe_trailing": _num(info.get("trailingPE")),
            "pe_forward": _num(info.get("forwardPE")),
            "peg_ratio": _num(info.get("pegRatio")) or _num(info.get("trailingPegRatio")),
            "pb": _num(info.get("priceToBook")),
            "ps": _num(info.get("priceToSalesTrailing12Months")),
            "ev_to_ebitda": _num(info.get("enterpriseToEbitda")),
            # 盈利与成长
            "eps_trailing": _num(info.get("trailingEps")),
            "eps_forward": _num(info.get("forwardEps")),
            "revenue": _num(info.get("totalRevenue")),
            "ebitda": _num(info.get("ebitda")),
            "profit_margin": _num(info.get("profitMargins")),
            "gross_margin": _num(info.get("grossMargins")),
            "operating_margin": _num(info.get("operatingMargins")),
            "roe": _num(info.get("returnOnEquity")),
            "roa": _num(info.get("returnOnAssets")),
            "revenue_growth": _num(info.get("revenueGrowth")),
            "earnings_growth": _num(info.get("earningsGrowth")),
            # 财务健康
            "debt_to_equity": _num(info.get("debtToEquity")),
            "current_ratio": _num(info.get("currentRatio")),
            "quick_ratio": _num(info.get("quickRatio")),
            "free_cashflow": _num(info.get("freeCashflow")),
            "total_cash": _num(info.get("totalCash")),
            "total_debt": _num(info.get("totalDebt")),
            # 股东回报
            "dividend_yield": _num(info.get("dividendYield")),
            "dividend_rate": _num(info.get("dividendRate")),
            "payout_ratio": _num(info.get("payoutRatio")),
            "beta": _num(info.get("beta")),
            # 分析师
            "target_mean": _num(info.get("targetMeanPrice")),
            "target_high": _num(info.get("targetHighPrice")),
            "target_low": _num(info.get("targetLowPrice")),
            "target_median": _num(info.get("targetMedianPrice")),
            "recommendation": _text(info.get("recommendationKey")),
            "recommendation_mean": _num(info.get("recommendationMean")),
            "analyst_count": _int(info.get("numberOfAnalystOpinions")),
            "earnings_date": _date_str(
                _get(info, "earningsTimestamp")
            ) or _date_str(_get(info, "earningsTimestampStart")),
            "ex_dividend_date": _date_str(info.get("exDividendDate")),
            "shares_outstanding": _num(info.get("sharesOutstanding")),
            "float_shares": _num(info.get("floatShares")),
            "held_by_insiders": _num(info.get("heldPercentInsiders")),
            "held_by_institutions": _num(info.get("heldPercentInstitutions")),
            "short_ratio": _num(info.get("shortRatio")),
            "short_pct_of_float": _num(info.get("shortPercentOfFloat")),
        }

    return _cached(f"profile:{market}:{symbol}", _INFO_TTL, load)


# --------------------------------------------------------------------------
# 财务报表
# --------------------------------------------------------------------------

_INCOME_ITEMS: dict[str, str] = {
    "Total Revenue": "revenue",
    "Gross Profit": "gross_profit",
    "Operating Income": "operating_income",
    "Pretax Income": "pretax_income",
    "Net Income": "net_income",
    "Diluted EPS": "diluted_eps",
    "Basic EPS": "basic_eps",
    "Research And Development": "rnd",
    "Selling General And Administration": "sga",
}

_BALANCE_ITEMS: dict[str, str] = {
    "Total Assets": "total_assets",
    "Current Assets": "current_assets",
    "Current Liabilities": "current_liabilities",
    "Total Liabilities Net Minority Interest": "total_liabilities",
    "Stockholders Equity": "equity",
    "Total Debt": "total_debt",
    "Cash And Cash Equivalents": "cash",
    "Inventory": "inventory",
    "Total Receivables": "receivables",
}

_CASHFLOW_ITEMS: dict[str, str] = {
    "Operating Cash Flow": "operating_cash_flow",
    "Investing Cash Flow": "investing_cash_flow",
    "Financing Cash Flow": "financing_cash_flow",
    "Free Cash Flow": "free_cash_flow",
    "Capital Expenditure": "capex",
    "Repurchase Of Capital Stock": "buyback",
    "Cash Dividends Paid": "dividends_paid",
}


def _statement_columns(frame: pd.DataFrame, limit: int) -> list:
    """取最近的 ``limit`` 个报告期（列名是 Timestamp）。"""
    try:
        columns = list(frame.columns)
    except Exception:  # noqa: BLE001
        return []
    columns = [c for c in columns if not pd.isna(c)]
    columns.sort(reverse=True)
    return columns[:limit]


def _extract_statement(
    frame: pd.DataFrame | None,
    item_map: dict[str, str],
    limit: int,
) -> dict[str, dict[str, float | None]]:
    """把报表转成 ``{报告期: {字段: 数值}}``。"""
    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
        return {}

    out: dict[str, dict[str, float | None]] = {}
    for column in _statement_columns(frame, limit):
        period = _date_str(column)
        if not period:
            continue
        row_values: dict[str, float | None] = {}
        for label, field in item_map.items():
            if label not in frame.index:
                continue
            try:
                row_values[field] = _num(frame.at[label, column])
            except Exception:  # noqa: BLE001
                row_values[field] = None
        out[period] = row_values
    return out


def _merge_periods(*sources: dict[str, dict]) -> dict[str, dict]:
    merged: dict[str, dict] = {}
    for source in sources:
        for period, values in (source or {}).items():
            merged.setdefault(period, {}).update(values)
    return merged


def _derive_financial_ratios(periods: dict[str, dict]) -> None:
    """就地补上利润率、同比增速等派生指标。"""
    ordered = sorted(periods.keys(), reverse=True)
    for index, period in enumerate(ordered):
        row = periods[period]
        revenue = row.get("revenue")
        net_income = row.get("net_income")

        if revenue:
            for field, key in (
                ("gross_profit", "gross_margin"),
                ("operating_income", "operating_margin"),
                ("net_income", "net_margin"),
                ("free_cash_flow", "fcf_margin"),
            ):
                value = row.get(field)
                row[key] = value / revenue if value is not None else None

        equity = row.get("equity")
        if equity and net_income is not None:
            row["roe"] = net_income / equity

        assets = row.get("total_assets")
        if assets and net_income is not None:
            row["roa"] = net_income / assets

        # 同比：与同类型的前一期比较（年报比年报，季报比季报）
        previous = periods.get(ordered[index + 1]) if index + 1 < len(ordered) else None
        if previous:
            for field, key in (
                ("revenue", "revenue_yoy"),
                ("net_income", "net_income_yoy"),
            ):
                current_value = row.get(field)
                previous_value = previous.get(field)
                if current_value and previous_value and previous_value != 0:
                    row[key] = current_value / previous_value - 1.0


def get_financials(symbol: str, market: str) -> dict | None:
    """近几期财务报表关键项 + 派生比率。"""

    def load() -> dict | None:
        ticker = _ticker(symbol, market)

        def safe(attr: str) -> pd.DataFrame | None:
            try:
                value = getattr(ticker, attr, None)
                return value if isinstance(value, pd.DataFrame) else None
            except Exception:  # noqa: BLE001
                return None

        annual = _merge_periods(
            _extract_statement(safe("income_stmt"), _INCOME_ITEMS, 5),
            _extract_statement(safe("balance_sheet"), _BALANCE_ITEMS, 5),
            _extract_statement(safe("cashflow"), _CASHFLOW_ITEMS, 5),
        )
        quarterly = _merge_periods(
            _extract_statement(safe("quarterly_income_stmt"), _INCOME_ITEMS, 8),
            _extract_statement(safe("quarterly_balance_sheet"), _BALANCE_ITEMS, 8),
            _extract_statement(safe("quarterly_cashflow"), _CASHFLOW_ITEMS, 8),
        )

        if not annual and not quarterly:
            return None

        _derive_financial_ratios(annual)
        _derive_financial_ratios(quarterly)

        return {
            "symbol": symbol,
            "market": market,
            "annual": annual,
            "quarterly": quarterly,
        }

    return _cached(f"financials:{market}:{symbol}", _STATEMENT_TTL, load)


# --------------------------------------------------------------------------
# 财报日历与盈利预测
# --------------------------------------------------------------------------

def _estimate_table(frame: pd.DataFrame | None, fields: dict[str, str]) -> dict[str, dict]:
    """把 ``earnings_estimate`` / ``revenue_estimate`` 这类表转成字典。"""
    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
        return {}
    out: dict[str, dict] = {}
    for period in frame.index:
        row: dict[str, Any] = {}
        for column, field in fields.items():
            if column in frame.columns:
                try:
                    row[field] = _num(frame.at[period, column])
                except Exception:  # noqa: BLE001
                    row[field] = None
        out[str(period)] = row
    return out


def get_earnings(symbol: str, market: str) -> dict | None:
    """财报日历、历史 EPS 意外、未来盈利/营收预测、EPS 修正趋势。"""

    def load() -> dict | None:
        ticker = _ticker(symbol, market)
        info = _info(ticker, symbol, market)

        # ---- 历史 EPS 意外 ----
        events: list[dict] = []
        frame = None
        try:
            if hasattr(ticker, "get_earnings_dates"):
                frame = ticker.get_earnings_dates(limit=12)
        except Exception:  # noqa: BLE001
            frame = None

        if frame is not None and isinstance(frame, pd.DataFrame) and not frame.empty:
            for index, row in frame.iterrows():
                date = _date_str(index)
                if not date:
                    continue
                events.append(
                    {
                        "date": date,
                        "eps_estimate": _num(_get(row, "EPS Estimate")),
                        "eps_actual": _num(_get(row, "Reported EPS")),
                        "surprise_pct": _num(_get(row, "Surprise(%)")),
                    }
                )
        events.sort(key=lambda item: item["date"], reverse=True)

        # ---- 下次财报日 ----
        next_date = None
        calendar: dict = {}
        try:
            raw_calendar = ticker.calendar
            if isinstance(raw_calendar, dict):
                calendar = raw_calendar
        except Exception:  # noqa: BLE001
            calendar = {}

        earnings_dates = calendar.get("Earnings Date") or []
        if isinstance(earnings_dates, (list, tuple)):
            for candidate in earnings_dates:
                parsed = _date_str(candidate)
                if parsed:
                    next_date = parsed
                    break
        elif earnings_dates:
            next_date = _date_str(earnings_dates)
        if next_date is None:
            next_date = _date_str(info.get("earningsTimestamp"))

        # ---- 未来预测 ----
        def safe_frame(attr: str) -> pd.DataFrame | None:
            try:
                value = getattr(ticker, attr, None)
                return value if isinstance(value, pd.DataFrame) else None
            except Exception:  # noqa: BLE001
                return None

        eps_estimate = _estimate_table(
            safe_frame("earnings_estimate"),
            {"avg": "avg", "low": "low", "high": "high", "numberOfAnalysts": "analysts", "growth": "growth", "yearAgoEps": "year_ago"},
        )
        revenue_estimate = _estimate_table(
            safe_frame("revenue_estimate"),
            {"avg": "avg", "low": "low", "high": "high", "numberOfAnalysts": "analysts", "growth": "growth", "yearAgoRevenue": "year_ago"},
        )
        eps_trend = _estimate_table(
            safe_frame("eps_trend"),
            {"current": "current", "7daysAgo": "d7", "30daysAgo": "d30", "90daysAgo": "d90"},
        )
        eps_revisions = _estimate_table(
            safe_frame("eps_revisions"),
            {"upLast7days": "up_7d", "upLast30days": "up_30d", "downLast7days": "down_7d", "downLast30days": "down_30d"},
        )

        if not events and not next_date and not eps_estimate:
            return None

        return {
            "symbol": symbol,
            "market": market,
            "next_earnings_date": next_date,
            "events": events[:8],
            "eps_estimate": eps_estimate,
            "revenue_estimate": revenue_estimate,
            "eps_trend": eps_trend,
            "eps_revisions": eps_revisions,
            "earnings_high": _num(calendar.get("Earnings High")),
            "earnings_low": _num(calendar.get("Earnings Low")),
            "earnings_average": _num(calendar.get("Earnings Average")),
            "revenue_average": _num(calendar.get("Revenue Average")),
        }

    return _cached(f"earnings:{market}:{symbol}", _EARNINGS_TTL, load)


# --------------------------------------------------------------------------
# 分析师观点
# --------------------------------------------------------------------------

def get_analyst(symbol: str, market: str) -> dict | None:
    def load() -> dict | None:
        ticker = _ticker(symbol, market)
        info = _info(ticker, symbol, market)

        targets: dict = {}
        try:
            raw = getattr(ticker, "analyst_price_targets", None)
            if isinstance(raw, dict):
                targets = raw
        except Exception:  # noqa: BLE001
            targets = {}

        recommendations: list[dict] = []
        try:
            frame = getattr(ticker, "recommendations", None)
            if isinstance(frame, pd.DataFrame) and not frame.empty:
                for _, row in frame.iterrows():
                    recommendations.append(
                        {
                            "period": _text(_get(row, "period")),
                            "strong_buy": _int(_get(row, "strongBuy")),
                            "buy": _int(_get(row, "buy")),
                            "hold": _int(_get(row, "hold")),
                            "sell": _int(_get(row, "sell")),
                            "strong_sell": _int(_get(row, "strongSell")),
                        }
                    )
        except Exception:  # noqa: BLE001
            recommendations = []

        # 机构与内部人持股
        holders: dict = {}
        try:
            frame = getattr(ticker, "major_holders", None)
            if isinstance(frame, pd.DataFrame) and not frame.empty:
                column = "Value" if "Value" in frame.columns else frame.columns[0]
                for label in frame.index:
                    holders[str(label)] = _num(frame.at[label, column])
        except Exception:  # noqa: BLE001
            holders = {}

        result = {
            "symbol": symbol,
            "market": market,
            "target_current": _num(targets.get("current")) or _num(info.get("currentPrice")),
            "target_high": _num(targets.get("high")) or _num(info.get("targetHighPrice")),
            "target_low": _num(targets.get("low")) or _num(info.get("targetLowPrice")),
            "target_mean": _num(targets.get("mean")) or _num(info.get("targetMeanPrice")),
            "target_median": _num(targets.get("median")) or _num(info.get("targetMedianPrice")),
            "recommendation_key": _text(info.get("recommendationKey")),
            "recommendation_mean": _num(info.get("recommendationMean")),
            "analyst_count": _int(info.get("numberOfAnalystOpinions")),
            "recommendations": recommendations,
            "holders": holders,
        }
        if not any(
            result[key] is not None
            for key in ("target_mean", "target_high", "recommendation_key", "analyst_count")
        ) and not recommendations:
            return None
        return result

    return _cached(f"analyst:{market}:{symbol}", _INFO_TTL, load)


# --------------------------------------------------------------------------
# 新闻
# --------------------------------------------------------------------------

def _parse_news_item(raw: dict) -> dict | None:
    """兼容 yfinance 新旧两种新闻结构。"""
    if not isinstance(raw, dict):
        return None

    content = raw.get("content") if isinstance(raw.get("content"), dict) else None
    source = content or raw

    title = _text(source.get("title")) or _text(raw.get("title"))
    if not title:
        return None

    publisher = None
    provider = source.get("provider")
    if isinstance(provider, dict):
        publisher = _text(provider.get("displayName"))
    if not publisher:
        publisher = _text(raw.get("publisher"))

    url = None
    for key in ("canonicalUrl", "clickThroughUrl", "previewUrl"):
        candidate = source.get(key)
        if isinstance(candidate, dict):
            url = _text(candidate.get("url"))
            if url:
                break
    if not url:
        url = _text(raw.get("link"))

    published = source.get("pubDate") or source.get("displayTime") or raw.get("providerPublishTime")
    published_at = None
    if isinstance(published, (int, float)):
        try:
            published_at = pd.to_datetime(published, unit="s", utc=True).isoformat()
        except Exception:  # noqa: BLE001
            published_at = None
    else:
        try:
            stamp = pd.to_datetime(published, errors="coerce", utc=True)
            published_at = None if pd.isna(stamp) else stamp.isoformat()
        except Exception:  # noqa: BLE001
            published_at = None

    summary = _text(source.get("summary")) or _text(source.get("description"))
    if summary and len(summary) > 400:
        summary = summary[:400] + "…"

    return {
        "title": title,
        "publisher": publisher,
        "url": url,
        "published_at": published_at,
        "summary": summary,
    }


def get_news(symbol: str, market: str, limit: int = 12) -> list[dict]:
    """近期新闻（含原文链接）。取不到返回空列表。"""

    def load() -> list[dict]:
        ticker = _ticker(symbol, market)
        items: list[dict] = []
        try:
            raw_items = getattr(ticker, "news", None) or []
            for raw in raw_items:
                parsed = _parse_news_item(raw)
                if parsed:
                    items.append(parsed)
        except Exception:  # noqa: BLE001
            items = []

        if not items:
            items = _news_from_rss(symbol, market)

        # 按标题去重，保持原有顺序
        seen: set[str] = set()
        deduped: list[dict] = []
        for item in items:
            key = item["title"].strip().lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    cached = _cached(f"news:{market}:{symbol}", _NEWS_TTL, load) or []
    return cached[:limit]


def _news_from_rss(symbol: str, market: str) -> list[dict]:
    """兜底：Yahoo Finance RSS。"""
    try:
        import httpx
        from email.utils import parsedate_to_datetime
        import xml.etree.ElementTree as ET
    except ImportError:  # pragma: no cover
        return []

    yf_symbol = to_yf_symbol(symbol, market)
    region = {"US": "US", "HK": "HK", "CN": "CN"}.get((market or "").upper(), "US")
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={yf_symbol}&region={region}&lang=en-US"

    try:
        with httpx.Client(timeout=8.0, headers={"User-Agent": "stock-mcpilot/1.0"}) as client:
            response = client.get(url)
        if response.status_code != 200 or not response.text:
            return []
        root = ET.fromstring(response.text)
        channel = root.find("channel")
        if channel is None:
            return []
        out: list[dict] = []
        for item in channel.findall("item"):
            title = (item.findtext("title") or "").strip()
            if not title:
                continue
            published = None
            raw_date = item.findtext("pubDate")
            if raw_date:
                try:
                    published = parsedate_to_datetime(raw_date).isoformat()
                except Exception:  # noqa: BLE001
                    published = None
            out.append(
                {
                    "title": title,
                    "publisher": "Yahoo Finance",
                    "url": (item.findtext("link") or "").strip() or None,
                    "published_at": published,
                    "summary": None,
                }
            )
        return out
    except Exception:  # noqa: BLE001
        return []


# --------------------------------------------------------------------------
# 代码搜索
# --------------------------------------------------------------------------

def search_symbols(query: str, limit: int = 10) -> list[dict]:
    """按关键字搜索标的（走 Yahoo 的 search 接口）。"""
    text = (query or "").strip()
    if not text:
        return []

    def load() -> list[dict]:
        try:
            import httpx

            with httpx.Client(timeout=8.0, headers={"User-Agent": "stock-mcpilot/1.0"}) as client:
                response = client.get(
                    "https://query2.finance.yahoo.com/v1/finance/search",
                    params={"q": text, "quotesCount": limit, "newsCount": 0, "listsCount": 0},
                )
            if response.status_code != 200:
                return []
            payload = response.json()
        except Exception:  # noqa: BLE001
            return []

        out: list[dict] = []
        for item in payload.get("quotes") or []:
            symbol = _text(item.get("symbol"))
            if not symbol:
                continue
            quote_type = _text(item.get("quoteType"))
            if quote_type not in ("EQUITY", "ETF", "MUTUALFUND", "INDEX", None):
                continue
            out.append(
                {
                    "symbol": symbol,
                    "market": _market_from_yf(symbol),
                    "name": _text(item.get("shortname")) or _text(item.get("longname")),
                    "exchange": _text(item.get("exchDisp")),
                    "type": quote_type,
                }
            )
        return out

    return _cached(f"search:{text.lower()}:{limit}", 3600.0, load) or []


def _market_from_yf(yf_symbol: str) -> str:
    upper = (yf_symbol or "").upper()
    if upper.endswith(".HK"):
        return "HK"
    if upper.endswith((".SS", ".SZ", ".BJ")):
        return "CN"
    return "US"
