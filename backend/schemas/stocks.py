from pydantic import BaseModel, Field
import pandas as pd

class StockAnalysisSummary(BaseModel):
    count: int
    mean_close: float
    vol_mean: float
    return_pct: float
    max_drawdown_pct: float
    volatility_pct: float = Field(..., description="近段时间收益标准差 *100")

    @classmethod
    def from_dataframe(cls, df: pd.DataFrame):
        close = df['close'] if 'close' in df.columns else df['Close']
        volume = df['volume'] if 'volume' in df.columns else df.get('Volume', close*0)
        ret_pct = (close.iloc[-1] / close.iloc[0] - 1) * 100
        rolling_max = close.cummax()
        drawdown = close/rolling_max - 1
        max_dd = drawdown.min() * 100
        vol = close.pct_change().std() * 100
        return cls(
            count=len(df),
            mean_close=float(close.mean()),
            vol_mean=float(volume.mean()),
            return_pct=float(ret_pct),
            max_drawdown_pct=float(max_dd),
            volatility_pct=float(vol),
        )

class StockDailyResponse(BaseModel):
    symbol: str
    market: str
    start: str
    end: str
    rows: list[dict]
    summary: StockAnalysisSummary
    company_name_en: str | None = None
    company_name_zh: str | None = None


class EarningsEvent(BaseModel):
    date: str
    eps_actual: float | None = None
    eps_estimate: float | None = None
    eps_surprise: float | None = None
    surprise_percent: float | None = None


class AnalystEstimates(BaseModel):
    next_quarter_eps_avg: float | None = None
    next_quarter_analysts: int | None = None
    next_year_eps_avg: float | None = None
    revenue_next_quarter_avg: float | None = None
    updated_at: str | None = None


class EarningsResponse(BaseModel):
    symbol: str
    market: str
    next_earnings_date: str | None = None
    events: list[EarningsEvent] = []
    analyst: AnalystEstimates | None = None


class NewsItem(BaseModel):
    published_at: str
    text: str


class NewsResponse(BaseModel):
    symbol: str
    market: str
    items: list[NewsItem] = []


class MoversItem(BaseModel):
    symbol: str
    name: str | None = None
    price: float | None = None
    change: float | None = None
    change_pct: float | None = None
    volume: int | None = None
    market_cap: float | None = None
    currency: str | None = None


class MoversResponse(BaseModel):
    market: str
    type: str  # 'gainers' | 'losers'
    count: int
    items: list[MoversItem] = []
