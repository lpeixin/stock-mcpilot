"""行情相关响应模型。

字段大多允许为 ``None`` —— 这是刻意的：不同市场、不同标的的数据可得性差异很大
（比如 A 股的"下次财报日"经常拿不到）。用 ``None`` 表示"该项无数据"，比填 0
或空串安全，前端也能据此显示占位符而不是误导性的数字。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Quote(BaseModel):
    symbol: str
    market: str
    name: str | None = None
    long_name: str | None = None
    name_zh: str | None = None
    price: float | None = None
    previous_close: float | None = None
    change: float | None = None
    change_pct: float | None = None
    open: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    volume: int | None = None
    avg_volume: int | None = None
    market_cap: float | None = None
    currency: str | None = None
    exchange: str | None = None
    quote_type: str | None = None
    week52_high: float | None = None
    week52_low: float | None = None
    week52_position_pct: float | None = None
    ma50: float | None = None
    ma200: float | None = None
    timezone: str | None = None


class Candle(BaseModel):
    date: str
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float | None = None
    # 指标列（随 indicators=true 返回）
    ma5: float | None = None
    ma10: float | None = None
    ma20: float | None = None
    ma60: float | None = None
    rsi14: float | None = None
    macd_dif: float | None = None
    macd_dea: float | None = None
    macd_hist: float | None = None
    boll_upper: float | None = None
    boll_mid: float | None = None
    boll_lower: float | None = None
    kdj_k: float | None = None
    kdj_d: float | None = None
    kdj_j: float | None = None
    atr14: float | None = None
    volume_ratio: float | None = None
    pct_change: float | None = None


class CandlesResponse(BaseModel):
    symbol: str
    market: str
    period: str
    interval: str
    count: int
    start: str | None = None
    end: str | None = None
    candles: list[Candle] = Field(default_factory=list)


class IndicatorSnapshot(BaseModel):
    close: float | None = None
    pct_change: float | None = None
    ma: dict[str, float | None] = Field(default_factory=dict)
    rsi14: float | None = None
    macd: dict[str, float | None] = Field(default_factory=dict)
    boll: dict[str, float | None] = Field(default_factory=dict)
    atr14: float | None = None
    atr_pct: float | None = None
    kdj: dict[str, float | None] = Field(default_factory=dict)
    volume_ratio: float | None = None
    amplitude: float | None = None
    #: 机器可读的形态判读，形如 ``[{"code": "rsi_zone", "params": {...}}]``。
    #: 前端按 code 自行本地化；``signals`` 是同一份数据的中文渲染。
    signals: list[str] = Field(default_factory=list)
    signals_structured: list[dict] = Field(default_factory=list)


class PriceSummary(BaseModel):
    count: int | None = None
    start_date: str | None = None
    end_date: str | None = None
    first_close: float | None = None
    last_close: float | None = None
    mean_close: float | None = None
    high: float | None = None
    low: float | None = None
    return_pct: float | None = None
    max_drawdown_pct: float | None = None
    volatility_pct: float | None = None
    annualized_volatility_pct: float | None = None
    max_single_day_gain_pct: float | None = None
    max_single_day_loss_pct: float | None = None
    up_days: int | None = None
    down_days: int | None = None
    vol_mean: float | None = None
    vol_last: float | None = None
    recent_20d_return_pct: float | None = None
    prior_20d_return_pct: float | None = None
    momentum_acceleration_pct: float | None = None


class StockDetailResponse(BaseModel):
    """个股详情：一次请求拿齐报价、指标快照、统计摘要与 K 线。"""

    symbol: str
    market: str
    quote: Quote | None = None
    indicators: IndicatorSnapshot | None = None
    summary: PriceSummary | None = None
    candles: list[Candle] = Field(default_factory=list)
    interval: str = "1d"
    period: str = "6mo"
    session: dict | None = None
    warnings: list[str] = Field(default_factory=list)


class NewsItem(BaseModel):
    title: str
    url: str | None = None
    publisher: str | None = None
    published_at: str | None = None
    summary: str | None = None


class NewsResponse(BaseModel):
    symbol: str
    market: str
    count: int
    items: list[NewsItem] = Field(default_factory=list)


class MoverItem(BaseModel):
    symbol: str
    market: str
    name: str | None = None
    name_zh: str | None = None
    price: float | None = None
    change: float | None = None
    change_pct: float | None = None
    volume: int | None = None
    market_cap: float | None = None
    currency: str | None = None
    exchange: str | None = None


class MoversResponse(BaseModel):
    market: str
    type: str
    count: int
    items: list[MoverItem] = Field(default_factory=list)


class UpcomingEarningsItem(BaseModel):
    symbol: str
    name: str | None = None
    earnings_date: str
    days_until: int | None = None
    eps_estimate: float | None = None
    market_cap: float | None = None
    currency: str | None = None


class UpcomingEarningsResponse(BaseModel):
    market: str
    count: int
    days: int
    items: list[UpcomingEarningsItem] = Field(default_factory=list)


class SearchResultItem(BaseModel):
    symbol: str
    market: str
    name: str | None = None
    exchange: str | None = None
    type: str | None = None


class SearchResponse(BaseModel):
    query: str
    count: int
    items: list[SearchResultItem] = Field(default_factory=list)
