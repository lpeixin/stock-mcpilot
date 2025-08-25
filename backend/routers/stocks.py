from datetime import date, timedelta
from fastapi import APIRouter, HTTPException, Query
from ..schemas.stocks import StockDailyResponse, StockAnalysisSummary
from functools import lru_cache
import yfinance as yf
from ..storage.cache import get_price_data

router = APIRouter()

@lru_cache(maxsize=512)
def _company_name(symbol: str, market: str):
    # Determine yfinance symbol as in storage.cache._market_symbol
    yf_symbol = symbol
    if market == 'HK' and not yf_symbol.endswith('.HK'):
        yf_symbol += '.HK'
    if market == 'CN':
        if symbol.startswith('6'):
            yf_symbol += '.SS'
        else:
            yf_symbol += '.SZ'
    try:
        t = yf.Ticker(yf_symbol)
        info = t.fast_info if hasattr(t, 'fast_info') else {}
        name = getattr(t, 'info', {}).get('shortName') if hasattr(t, 'info') else None
        if not name and isinstance(info, dict):
            name = info.get('shortName') or info.get('longName')
        return name
    except Exception:
        return None

@router.get("/{symbol}", response_model=StockDailyResponse)
def get_stock_daily(symbol: str, market: str = Query("US", regex="^(US|HK|CN)$"), days: int = 60):
    symbol = symbol.upper().strip()
    end = date.today()
    start = end - timedelta(days=days*2)  # buffer for non-trading days
    try:
        df = get_price_data(symbol=symbol, market=market, start=start, end=end)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if df.empty:
        raise HTTPException(status_code=404, detail="No data")
    df = df.tail(days)
    summary = StockAnalysisSummary.from_dataframe(df)
    # 统一前端所需行结构: date 字段
    df_out = df.copy()
    # 处理已有 'date' 列冲突：如果数据里已经有 date 列，则用临时索引名再改回
    index_name = 'date'
    if 'date' in df_out.columns:
        index_name = '_date_index'
    df_out.index.name = index_name
    df_rows = df_out.reset_index()
    if index_name != 'date':
        # 如果已有 date 列且内容与索引重复，优先使用索引值覆盖旧列
        if 'date' in df_rows.columns:
            # 尝试检测是否可转换为日期；保留索引版本
            df_rows.drop(columns=['date'], inplace=True, errors='ignore')
        df_rows.rename(columns={index_name: 'date'}, inplace=True)
    rows = df_rows.to_dict(orient="records")
    name_en = _company_name(symbol, market)
    # Placeholder: Chinese name resolution could be added via akshare later.
    name_zh = None
    return StockDailyResponse(
        symbol=symbol,
        market=market,
        start=str(df.index.min().date()),
        end=str(df.index.max().date()),
        rows=rows,
        summary=summary,
        company_name_en=name_en,
        company_name_zh=name_zh
    )
