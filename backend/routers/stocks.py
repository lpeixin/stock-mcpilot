from datetime import date, timedelta
from fastapi import APIRouter, HTTPException, Query
from ..schemas.stocks import StockDailyResponse, StockAnalysisSummary
from ..storage.cache import get_price_data

router = APIRouter()

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
    return StockDailyResponse(
        symbol=symbol,
        market=market,
        start=str(df.index.min().date()),
        end=str(df.index.max().date()),
        rows=rows,
        summary=summary
    )
