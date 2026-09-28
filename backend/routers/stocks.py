"""行情路由。

路由注册顺序很重要：``/search``、``/movers``、``/upcoming_earnings`` 这些**静态
路径必须排在 ``/{symbol}`` 之前**，否则会被动态路径捕获 —— 改造前就有两个同名
``upcoming_earnings`` 处理函数（前者侥幸生效，后者是死代码），正是这个坑的产物。

路径一律不带尾斜杠，避免 FastAPI 的 307 重定向（旧 ``/settings`` 就踩过）。
"""

from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, HTTPException, Path, Query

from ..marketdata import cn_names, movers, yf_client
from ..schemas.stocks import (
    Candle,
    CandlesResponse,
    IndicatorSnapshot,
    MoverItem,
    MoversResponse,
    NewsItem,
    NewsResponse,
    PriceSummary,
    Quote,
    SearchResponse,
    SearchResultItem,
    StockDetailResponse,
    UpcomingEarningsItem,
    UpcomingEarningsResponse,
)
from ..storage import cache

router = APIRouter()

_SYMBOL_PATTERN = r"^[A-Za-z0-9\.\-]{1,16}$"
_CANDLE_COLUMNS = (
    "open", "high", "low", "close", "volume", "pct_change",
    "ma5", "ma10", "ma20", "ma60",
    "rsi14",
    "macd_dif", "macd_dea", "macd_hist",
    "boll_upper", "boll_mid", "boll_lower",
    "kdj_k", "kdj_d", "kdj_j",
    "atr14", "volume_ratio",
)


def _clean_symbol(symbol: str) -> str:
    return symbol.upper().strip()


def _frame_to_candles(frame: pd.DataFrame) -> list[Candle]:
    if frame is None or frame.empty:
        return []
    out: list[Candle] = []
    for index, row in frame.iterrows():
        payload: dict = {"date": str(pd.to_datetime(index).date())}
        for column in _CANDLE_COLUMNS:
            if column not in frame.columns:
                continue
            value = row.get(column)
            try:
                number = float(value)
            except (TypeError, ValueError):
                number = None
            payload[column] = None if (number is None or number != number) else number
        out.append(Candle(**payload))
    return out


def _with_chinese_name(quote: dict | None, symbol: str, market: str) -> dict | None:
    """A 股补一个中文简称（akshare 可选增强，失败即跳过）。"""
    if quote is None or market != "CN":
        return quote
    name_zh = cn_names.get_cn_name(symbol, market)
    if name_zh:
        quote = {**quote, "name_zh": name_zh}
    return quote


# --------------------------------------------------------------------------
# 静态路径（必须放在 /{symbol} 之前）
# --------------------------------------------------------------------------

@router.get("/search", response_model=SearchResponse)
def search(
    q: str = Query(..., min_length=1, max_length=32, description="代码或公司名关键字"),
    limit: int = Query(10, ge=1, le=25),
) -> SearchResponse:
    """按关键字搜索标的。"""
    raw = yf_client.search_symbols(q, limit=limit)
    items = [
        SearchResultItem(
            symbol=item.get("symbol", ""),
            market=item.get("market", "US"),
            name=item.get("name"),
            exchange=item.get("exchange"),
            type=item.get("type"),
        )
        for item in raw
        if item.get("symbol")
    ]
    return SearchResponse(query=q, count=len(items), items=items)


@router.get("/movers", response_model=MoversResponse)
def get_movers(
    market: str = Query("US", pattern="^(US|HK|CN)$"),
    type: str = Query("gainers", pattern="^(gainers|losers)$"),
    count: int = Query(10, ge=1, le=50),
) -> MoversResponse:
    """涨幅榜 / 跌幅榜。"""
    raw = movers.get_movers(market, type, count)
    items = [MoverItem(**item) for item in raw]
    return MoversResponse(market=market, type=type, count=len(items), items=items)


@router.get("/upcoming_earnings", response_model=UpcomingEarningsResponse)
def get_upcoming_earnings(
    market: str = Query("US", pattern="^(US|HK|CN)$"),
    days: int = Query(14, ge=1, le=90),
    limit: int = Query(50, ge=1, le=200),
) -> UpcomingEarningsResponse:
    """未来若干天的财报安排（基于权重股标的池并发查询，结果缓存 30 分钟）。"""
    raw = movers.get_upcoming_earnings(market, days=days, limit=limit)
    items = [
        UpcomingEarningsItem(
            symbol=item["symbol"],
            name=item.get("name"),
            earnings_date=item["earnings_date"],
            days_until=item.get("days_until"),
            eps_estimate=item.get("eps_estimate"),
            market_cap=item.get("market_cap"),
            currency=item.get("currency"),
        )
        for item in raw
    ]
    return UpcomingEarningsResponse(market=market, count=len(items), days=days, items=items)


@router.get("/cn_names_status")
def cn_names_status() -> dict:
    """akshare 中文名增强的可用状态（供设置页诊断）。"""
    return cn_names.status()


# --------------------------------------------------------------------------
# 个股
# --------------------------------------------------------------------------

@router.get("/{symbol}", response_model=StockDetailResponse)
def get_stock_detail(
    symbol: str = Path(..., pattern=_SYMBOL_PATTERN),
    market: str = Query("US", pattern="^(US|HK|CN)$"),
    period: str = Query("6mo", pattern="^(1mo|3mo|6mo|1y|2y|5y|10y|ytd|max)$"),
    interval: str = Query("1d", pattern="^(1d|1wk|1mo)$"),
    days: int = Query(180, ge=20, le=1000, description="统计摘要与指标所用的回溯天数"),
) -> StockDetailResponse:
    """个股详情：报价 + 指标快照 + 统计摘要 + K 线。"""
    code = _clean_symbol(symbol)
    warnings: list[str] = []

    quote = _with_chinese_name(yf_client.get_quote(code, market), code, market)
    if quote is None:
        warnings.append("未能获取报价数据，请确认代码与市场是否正确。")

    # 指标与统计基于日线；周线/月线仅用于绘图
    frame = cache.get_price_frame_with_indicators(code, market, days)
    if frame.empty:
        warnings.append("未能获取历史行情。")

    # 盘中刷新当日那根
    try:
        cache.maybe_update_intraday(code, market)
    except Exception:  # noqa: BLE001 - 实时刷新失败不应影响主流程
        warnings.append("实时行情刷新失败，展示的是最近一次缓存数据。")

    from ..analysis import indicators as ind

    snapshot = ind.latest_snapshot(frame) if not frame.empty else {}
    if snapshot:
        snapshot["signals"] = ind.derive_signals(snapshot)
        snapshot["signals_structured"] = ind.derive_signals_structured(snapshot)
    summary = ind.compute_summary(frame) if not frame.empty else {}

    candle_frame, used_interval = cache.get_candles(code, market, period=period, interval=interval)
    candles = _frame_to_candles(candle_frame)

    return StockDetailResponse(
        symbol=code,
        market=market,
        quote=Quote(**quote) if quote else None,
        indicators=IndicatorSnapshot(**snapshot) if snapshot else None,
        summary=PriceSummary(**summary) if summary else None,
        candles=candles,
        interval=used_interval,
        period=period,
        session=cache.market_session(market),
        warnings=warnings,
    )


@router.get("/{symbol}/candles", response_model=CandlesResponse)
def get_candles(
    symbol: str = Path(..., pattern=_SYMBOL_PATTERN),
    market: str = Query("US", pattern="^(US|HK|CN)$"),
    period: str = Query("6mo", pattern="^(1mo|3mo|6mo|1y|2y|5y|10y|ytd|max)$"),
    interval: str = Query("1d", pattern="^(1d|1wk|1mo|1m|5m|15m|30m|60m)$"),
) -> CandlesResponse:
    """按周期与频率取 K 线。切换图表周期时单独调用，避免重取报价与财报。"""
    code = _clean_symbol(symbol)
    frame, used_interval = cache.get_candles(code, market, period=period, interval=interval)
    candles = _frame_to_candles(frame)
    return CandlesResponse(
        symbol=code,
        market=market,
        period=period,
        interval=used_interval,
        count=len(candles),
        start=candles[0].date if candles else None,
        end=candles[-1].date if candles else None,
        candles=candles,
    )


@router.get("/{symbol}/quote", response_model=Quote)
def get_quote(
    symbol: str = Path(..., pattern=_SYMBOL_PATTERN),
    market: str = Query("US", pattern="^(US|HK|CN)$"),
) -> Quote:
    code = _clean_symbol(symbol)
    data = _with_chinese_name(yf_client.get_quote(code, market), code, market)
    if not data:
        raise HTTPException(status_code=404, detail=f"未找到 {code} 的报价数据。")
    return Quote(**data)


@router.get("/{symbol}/profile")
def get_profile(
    symbol: str = Path(..., pattern=_SYMBOL_PATTERN),
    market: str = Query("US", pattern="^(US|HK|CN)$"),
) -> dict:
    """公司概况与估值指标。"""
    code = _clean_symbol(symbol)
    data = yf_client.get_profile(code, market)
    if not data:
        raise HTTPException(status_code=404, detail=f"未找到 {code} 的公司概况。")
    name_zh = cn_names.get_cn_name(code, market)
    if name_zh:
        data = {**data, "name_zh": name_zh}
    return data


@router.get("/{symbol}/financials")
def get_financials(
    symbol: str = Path(..., pattern=_SYMBOL_PATTERN),
    market: str = Query("US", pattern="^(US|HK|CN)$"),
) -> dict:
    """近几期财务报表关键项与派生比率。"""
    code = _clean_symbol(symbol)
    data = yf_client.get_financials(code, market)
    if not data:
        raise HTTPException(status_code=404, detail=f"未找到 {code} 的财务报表数据。")
    return data


@router.get("/{symbol}/earnings")
def get_earnings(
    symbol: str = Path(..., pattern=_SYMBOL_PATTERN),
    market: str = Query("US", pattern="^(US|HK|CN)$"),
) -> dict:
    """财报日历、历史 EPS 意外、未来盈利与营收预测。"""
    code = _clean_symbol(symbol)
    data = yf_client.get_earnings(code, market)
    if not data:
        raise HTTPException(status_code=404, detail=f"未找到 {code} 的财报数据。")
    return data


@router.get("/{symbol}/analyst")
def get_analyst(
    symbol: str = Path(..., pattern=_SYMBOL_PATTERN),
    market: str = Query("US", pattern="^(US|HK|CN)$"),
) -> dict:
    """分析师目标价、评级分布与持股结构。"""
    code = _clean_symbol(symbol)
    data = yf_client.get_analyst(code, market)
    if not data:
        raise HTTPException(status_code=404, detail=f"未找到 {code} 的分析师数据。")
    return data


@router.get("/{symbol}/news", response_model=NewsResponse)
def get_news(
    symbol: str = Path(..., pattern=_SYMBOL_PATTERN),
    market: str = Query("US", pattern="^(US|HK|CN)$"),
    limit: int = Query(12, ge=1, le=40),
) -> NewsResponse:
    """近期新闻（含原文链接）。"""
    code = _clean_symbol(symbol)
    raw = yf_client.get_news(code, market, limit=limit)

    # 顺带写入本地库，保留跨会话的资讯痕迹；写失败不影响返回。
    try:
        from ..storage.db import add_news_items

        add_news_items(code, market, raw)
    except Exception:  # noqa: BLE001
        pass

    items = [
        NewsItem(
            title=item.get("title", ""),
            url=item.get("url"),
            publisher=item.get("publisher"),
            published_at=item.get("published_at"),
            summary=item.get("summary"),
        )
        for item in raw
        if item.get("title")
    ]
    return NewsResponse(symbol=code, market=market, count=len(items), items=items)
