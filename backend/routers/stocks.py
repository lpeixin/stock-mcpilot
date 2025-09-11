from datetime import date, timedelta
from fastapi import APIRouter, HTTPException, Query
from ..schemas.stocks import StockDailyResponse, StockAnalysisSummary, EarningsResponse, EarningsEvent, AnalystEstimates
from functools import lru_cache
import yfinance as yf
from ..storage.cache import get_price_data, maybe_update_intraday

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
    # Intraday update: if market open, attempt to update today's row with live price
    try:
        updated = maybe_update_intraday(symbol, market)
        if updated:
            # incorporate into df
            import pandas as pd
            idx = pd.to_datetime([updated['date']])
            if df.empty:
                df = pd.DataFrame([updated]).set_index(idx)
            else:
                # replace or append
                if pd.to_datetime(updated['date']) in df.index:
                    df.loc[pd.to_datetime(updated['date']), ['open','high','low','close','volume']] = [updated.get('open'), updated.get('high'), updated.get('low'), updated.get('close'), updated.get('volume')]
                else:
                    df.loc[pd.to_datetime(updated['date']), ['open','high','low','close','volume']] = [updated.get('open'), updated.get('high'), updated.get('low'), updated.get('close'), updated.get('volume')]
            df = df.sort_index()
    except Exception:
        pass  # fail silently for live updates
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


@router.get("/{symbol}/earnings", response_model=EarningsResponse)
def get_stock_earnings(symbol: str, market: str = Query("US", regex="^(US|HK|CN)$")):
    symbol = symbol.upper().strip()
    # Map to yfinance symbol similar to cache._market_symbol
    yf_symbol = symbol
    if market == 'HK' and not yf_symbol.endswith('.HK'):
        yf_symbol += '.HK'
    if market == 'CN':
        if symbol.startswith('6'):
            yf_symbol += '.SS'
        else:
            yf_symbol += '.SZ'
    t = yf.Ticker(yf_symbol)
    events: list[EarningsEvent] = []
    next_earnings_date: str | None = None
    analyst: AnalystEstimates | None = None
    # Calendar / next earnings date (best-effort parsing)
    try:
        cal = None
        for attr in ['get_calendar', 'calendar']:
            v = getattr(t, attr, None)
            try:
                cal = v() if callable(v) else v
                if cal is not None and hasattr(cal, 'empty') and not cal.empty:
                    break
            except Exception:
                continue
        if cal is not None and hasattr(cal, 'to_dict'):
            # normalize to dict of lists
            d = cal.to_dict()
            # flatten possible values and pick date-like
            candidates = []
            for k, vals in d.items():
                if isinstance(vals, dict):
                    vals = list(vals.values())
                for v in (vals or []):
                    candidates.append(v)
            for v in candidates:
                try:
                    if hasattr(v, 'date'):
                        next_earnings_date = str(v.date())
                        break
                    # try parse pandas Timestamp-like
                    import pandas as pd
                    ts = pd.to_datetime(v, errors='ignore')
                    if hasattr(ts, 'date'):
                        next_earnings_date = str(ts.date())
                        break
                except Exception:
                    continue
    except Exception:
        pass

    # Earnings events: try multiple methods across yfinance versions
    df = None
    try:
        # Preferred
        if hasattr(t, 'get_earnings_dates'):
            df = t.get_earnings_dates(limit=16)  # ~4 years max; we'll tail 8
    except Exception:
        df = None
    if df is None:
        try:
            cand = getattr(t, 'earnings_dates', None)
            df = cand() if callable(cand) else cand
        except Exception:
            df = None
    try:
        if df is not None and not df.empty:
            # unify columns
            rename_map = {}
            for c in df.columns:
                lc = str(c).lower()
                if 'eps' in lc and 'actual' in lc:
                    rename_map[c] = 'eps_actual'
                elif 'eps' in lc and ('estimate' in lc or 'est' in lc):
                    rename_map[c] = 'eps_estimate'
                elif 'surprise' in lc and '%' in lc:
                    rename_map[c] = 'surprise_percent'
                elif 'surprise' in lc:
                    rename_map[c] = 'eps_surprise'
            df2 = df.rename(columns=rename_map)
            df2 = df2.sort_index().tail(8)
            for idx, row in df2.iterrows():
                events.append(EarningsEvent(
                    date=str(idx.date()) if hasattr(idx, 'date') else str(idx),
                    eps_actual=float(row['eps_actual']) if 'eps_actual' in row and row['eps_actual'] == row['eps_actual'] else None,
                    eps_estimate=float(row['eps_estimate']) if 'eps_estimate' in row and row['eps_estimate'] == row['eps_estimate'] else None,
                    eps_surprise=float(row['eps_surprise']) if 'eps_surprise' in row and row['eps_surprise'] == row['eps_surprise'] else None,
                    surprise_percent=float(row['surprise_percent']) if 'surprise_percent' in row and row['surprise_percent'] == row['surprise_percent'] else None,
                ))
    except Exception:
        pass
    try:
        fi = getattr(t, 'fast_info', {}) or {}
        def _fi(k):
            if isinstance(fi, dict):
                return fi.get(k)
            return getattr(fi, k, None)
        analyst = AnalystEstimates(
            next_quarter_eps_avg=None,
            next_quarter_analysts=None,
            next_year_eps_avg=None,
            revenue_next_quarter_avg=None,
            updated_at=None
        )
        # yfinance doesn't provide analyst consensus uniformly; left as None to avoid misleading data
    except Exception:
        analyst = None
    return EarningsResponse(symbol=symbol, market=market, next_earnings_date=next_earnings_date, events=events, analyst=analyst)
