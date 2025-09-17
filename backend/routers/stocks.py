from datetime import date, timedelta
from fastapi import APIRouter, HTTPException, Query, Path
from ..schemas.stocks import StockDailyResponse, StockAnalysisSummary, EarningsResponse, EarningsEvent, AnalystEstimates, NewsResponse, NewsItem, MoversResponse, MoversItem
from ..schemas.stocks import UpcomingEarningsResponse, UpcomingEarningsItem
from functools import lru_cache
import yfinance as yf
from ..storage.cache import get_price_data, maybe_update_intraday, fetch_news
from ..storage.db import load_news, add_news_items

router = APIRouter()

@router.get("/movers", response_model=MoversResponse)
def get_top_movers(market: str = Query("US", regex="^(US|HK|CN)$"), type: str = Query("gainers", regex="^(gainers|losers)$"), count: int = Query(10, ge=1, le=20)):
    import httpx
    # Map to Yahoo Finance screener tags (attempt specific then generic)
    screener = None
    if market == 'US':
        screener_candidates = ['day_gainers' if type == 'gainers' else 'day_losers', 'most_actives']
    else:
        # Try dedicated gainers/losers first; Yahoo sometimes supports these regionally
        screener_candidates = ['day_gainers' if type == 'gainers' else 'day_losers', 'most_actives']
    region = {'US':'US','HK':'HK','CN':'CN'}.get(market, 'US')
    lang = 'en-US'
    base1 = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
    base2 = "https://query2.finance.yahoo.com/v1/finance/screener/predefined/saved"
    def _urls(scr: str):
        return (
            f"{base1}?lang={lang}&region={region}&count={count}&scrIds={scr}",
            f"{base2}?lang={lang}&region={region}&count={count}&scrIds={scr}",
        )
    items: list[MoversItem] = []
    try:
        with httpx.Client(timeout=8.0, headers={"User-Agent": "stock-mcpilot/1.0"}) as client:
            # try primary, then secondary host
            quotes = []
            # Iterate screener candidates until we get quotes
            quotes = []
            for scr in screener_candidates:
                url1, url2 = _urls(scr)
                for url in (url1, url2):
                    r = client.get(url)
                    if r.status_code == 200:
                        data = r.json()
                        quotes = (((data or {}).get('finance') or {}).get('result') or [{}])[0].get('quotes') or []
                        if quotes:
                            break
                if quotes:
                    break
                # For HK/CN fallbacks we accept result then post-filter by change sign if available
            raw_items = quotes
            # If US and requested screener failed (empty), fallback to most_actives then sort by change_pct
            if market == 'US' and not items:
                for url in (f"{base1}?lang={lang}&region=US&count=50&scrIds=most_actives", f"{base2}?lang={lang}&region=US&count=50&scrIds=most_actives"):
                    r = client.get(url)
                    if r.status_code == 200:
                        data = r.json()
                        quotes = (((data or {}).get('finance') or {}).get('result') or [{}])[0].get('quotes') or []
                        if quotes:
                            tmp = []
                            for q in quotes:
                                chg = q.get('regularMarketChange')
                                price = q.get('regularMarketPrice')
                                prev_close = q.get('regularMarketPreviousClose')
                                if prev_close is None and (price is not None and chg is not None):
                                    try:
                                        prev_close = float(price) - float(chg)
                                    except Exception:
                                        prev_close = None
                                calc_pct = None
                                try:
                                    if chg is not None and prev_close not in (None, 0):
                                        calc_pct = (float(chg) / float(prev_close)) * 100.0
                                except Exception:
                                    calc_pct = None
                                if calc_pct is None and q.get('regularMarketChangePercent') is not None:
                                    try:
                                        calc_pct = float(q.get('regularMarketChangePercent'))
                                    except Exception:
                                        calc_pct = None
                                sym_fb = q.get('symbol')
                                tmp.append({
                                    'symbol': sym_fb,
                                    'name': q.get('shortName') or q.get('longName'),
                                    'price': price,
                                    'change': chg,
                                    'change_pct': calc_pct,
                                    'volume': q.get('regularMarketVolume'),
                                    'market_cap': q.get('marketCap'),
                                    'currency': q.get('currency'),
                                })
                            if type == 'gainers':
                                tmp.sort(key=lambda x: (x['change_pct'] or 0), reverse=True)
                            else:
                                tmp.sort(key=lambda x: (x['change_pct'] or 0))
                            for q in tmp[:count]:
                                items.append(MoversItem(**q))
                            break
            # Strict market filtering
            def _is_us(sym: str) -> bool:
                return not (sym.endswith('.HK') or sym.endswith('.SS') or sym.endswith('.SZ'))
            def _is_hk(sym: str) -> bool:
                return sym.endswith('.HK')
            def _is_cn(sym: str) -> bool:
                return sym.endswith('.SS') or sym.endswith('.SZ')

            def _match_symbol(sym: str) -> bool:
                if market == 'US':
                    return _is_us(sym)
                if market == 'HK':
                    return _is_hk(sym)
                if market == 'CN':
                    return _is_cn(sym)
                return False

            filtered_quotes = []
            for q in (raw_items or []):
                sym = (q.get('symbol') or '').upper()
                if not sym:
                    continue
                if not _match_symbol(sym):
                    continue
                filtered_quotes.append(q)

            if not filtered_quotes:
                # No genuine symbols for requested market; return empty
                return MoversResponse(market=market, type=type, count=0, items=[])

            # Build items only from filtered quotes
            items = []
            for q in filtered_quotes:
                chg = q.get('regularMarketChange')
                chgp_raw = q.get('regularMarketChangePercent')
                sym = q.get('symbol') or ''
                cur = q.get('currency')
                price = q.get('regularMarketPrice')
                prev_close = q.get('regularMarketPreviousClose')
                if prev_close is None and (price is not None and chg is not None):
                    try:
                        prev_close = float(price) - float(chg)
                    except Exception:
                        prev_close = None
                change_pct = None
                try:
                    if chg is not None and prev_close not in (None, 0):
                        change_pct = (float(chg) / float(prev_close)) * 100.0
                except Exception:
                    change_pct = None
                if change_pct is None and chgp_raw is not None:
                    try:
                        change_pct = float(chgp_raw)
                    except Exception:
                        change_pct = None
                items.append(MoversItem(
                    symbol=sym,
                    name=q.get('shortName') or q.get('longName'),
                    price=price,
                    change=chg,
                    change_pct=change_pct,
                    volume=q.get('regularMarketVolume'),
                    market_cap=q.get('marketCap'),
                    currency=cur,
                ))

            # Sign filtering and sorting for all markets
            if items:
                signed = [it for it in items if ((it.change_pct or 0) >= 0)] if type == 'gainers' else [it for it in items if ((it.change_pct or 0) < 0)]
                if not signed:
                    return MoversResponse(market=market, type=type, count=0, items=[])
                signed.sort(key=lambda x: (x.change_pct or 0), reverse=(type == 'gainers'))
                items = signed[:count]
    except Exception:
        items = []
    return MoversResponse(market=market, type=type, count=len(items), items=items)

@router.get("/upcoming_earnings", response_model=UpcomingEarningsResponse)
def get_upcoming_earnings(market: str = Query("US", regex="^(US|HK|CN)$"), days: int = Query(14, ge=1, le=60), limit: int = Query(50, ge=1, le=200)):
    """Return upcoming earnings (best-effort).

    NOTE: Placed before dynamic /{symbol} route to avoid path parameter capture causing 404/422.

    Current implementation:
    - US: Iterate a representative symbol universe and query yfinance for forward earnings dates.
    - HK/CN: Placeholder returns empty (future enhancement: integrate akshare or other sources).
    """
    items: list[UpcomingEarningsItem] = []
    from datetime import datetime, timedelta as _td
    end_date = datetime.utcnow().date() + _td(days=days)
    if market == 'US':
        sample_symbols = [
            'AAPL','MSFT','AMZN','GOOGL','META','NVDA','TSLA','ORCL','INTC','NFLX','CRM','AMD','QCOM','CSCO','ADBE','PYPL','PEP','COST','AVGO','TXN',
            'JPM','BAC','WFC','V','MA','KO','PFE','ABBV','MRK','XOM','CVX','UNH','HD','WMT','DIS','NKE','LIN','TMO','ABNB','SNOW','SHOP'
        ]
        import yfinance as _yf, pandas as _pd
        today = datetime.utcnow().date()
        for sym in sample_symbols:
            if len(items) >= limit:
                break
            try:
                tkr = _yf.Ticker(sym)
                earns_df = None
                if hasattr(tkr, 'get_earnings_dates'):
                    try:
                        earns_df = tkr.get_earnings_dates(limit=12)
                    except Exception:
                        earns_df = None
                future_date = None
                if earns_df is not None and not earns_df.empty:
                    for idx in earns_df.index:
                        try:
                            d = idx.date() if hasattr(idx, 'date') else _pd.to_datetime(idx).date()
                            if d >= today and d <= end_date:
                                future_date = d; break
                        except Exception:
                            continue
                if future_date is None:
                    cal = None
                    for attr in ['get_calendar','calendar']:
                        v = getattr(tkr, attr, None)
                        try:
                            cal = v() if callable(v) else v
                            if cal is not None and hasattr(cal,'empty') and not cal.empty:
                                break
                        except Exception:
                            continue
                    if cal is not None and hasattr(cal,'to_dict'):
                        dct = cal.to_dict(); flat = []
                        for k, vs in dct.items():
                            if isinstance(vs, dict): vs = list(vs.values())
                            for vv in (vs or []): flat.append(vv)
                        for vv in flat:
                            try:
                                ts = _pd.to_datetime(vv, errors='coerce')
                                if ts is not None and ts is not _pd.NaT:
                                    dd = ts.date()
                                    if dd >= today and dd <= end_date:
                                        future_date = dd; break
                            except Exception:
                                continue
                if future_date:
                    short_name = None
                    try:
                        info = getattr(tkr, 'info', {}) if hasattr(tkr, 'info') else {}
                        if isinstance(info, dict):
                            short_name = info.get('shortName') or info.get('longName')
                    except Exception:
                        short_name = None
                    items.append(UpcomingEarningsItem(symbol=sym, name=short_name, earnings_date=str(future_date), session=None))
            except Exception:
                continue
        items.sort(key=lambda x: x.earnings_date or '')
    else:
        items = []
    return UpcomingEarningsResponse(market=market, count=len(items), items=items)

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
def get_stock_daily(
    symbol: str = Path(..., regex=r"^[A-Za-z0-9\.]{1,15}$"),
    market: str = Query("US", regex="^(US|HK|CN)$"),
    days: int = 60
):
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


@router.get("/{symbol}/news", response_model=NewsResponse)
def get_stock_news(symbol: str, market: str = Query("US", regex="^(US|HK|CN)$")):
    symbol = symbol.upper().strip()
    # try cache first
    cached = load_news(symbol, market)
    items: list[NewsItem] = [NewsItem(published_at=str(r['published_at']), text=r['text']) for r in cached]
    # fetch fresh best-effort, then upsert and return top 10
    fresh = fetch_news(symbol, market)
    if fresh:
        try:
            add_news_items(symbol, market, fresh)
            cached = load_news(symbol, market)
            items = [NewsItem(published_at=str(r['published_at']), text=r['text']) for r in cached]
        except Exception:
            pass
    return NewsResponse(symbol=symbol, market=market, items=items[:10])


@router.get("/upcoming_earnings", response_model=UpcomingEarningsResponse)
def get_upcoming_earnings(market: str = Query("US", regex="^(US|HK|CN)$"), days: int = Query(14, ge=1, le=60), limit: int = Query(50, ge=1, le=200)):
    """Return upcoming earnings (best-effort).

    Current implementation:
    - US: Scrape yfinance earnings calendar via tickers derived from major indices ETFs components fallback (simplified) or yfinance calendar endpoints if accessible.
    - HK/CN: Placeholder returns empty (akshare integration could be added later).
    """
    items: list[UpcomingEarningsItem] = []
    from datetime import datetime, timedelta
    end_date = datetime.utcnow().date() + timedelta(days=days)
    if market == 'US':
        # Broaden sample list (top weights of S&P/Nasdaq + a few others)
        sample_symbols = [
            'AAPL','MSFT','AMZN','GOOGL','META','NVDA','TSLA','ORCL','INTC','NFLX','CRM','AMD','QCOM','CSCO','ADBE','PYPL','PEP','COST','AVGO','TXN',
            'JPM','BAC','WFC','V','MA','KO','PFE','ABBV','MRK','XOM','CVX','UNH','HD','WMT','DIS','NKE','LIN','TMO','ABNB','SNOW','SHOP'
        ]
        import yfinance as yf, pandas as pd
        today = datetime.utcnow().date()
        for sym in sample_symbols:
            if len(items) >= limit:
                break
            try:
                t = yf.Ticker(sym)
                # Try get_earnings_dates first for forward dates
                earns_df = None
                if hasattr(t, 'get_earnings_dates'):
                    try:
                        earns_df = t.get_earnings_dates(limit=12)
                    except Exception:
                        earns_df = None
                future_date = None
                if earns_df is not None and not earns_df.empty:
                    # index holds dates; pick the first date >= today within window
                    for idx in earns_df.index:
                        try:
                            d = idx.date() if hasattr(idx, 'date') else pd.to_datetime(idx).date()
                            if d >= today and d <= end_date:
                                future_date = d
                                break
                        except Exception:
                            continue
                # Fallback to calendar
                if future_date is None:
                    cal = None
                    for attr in ['get_calendar','calendar']:
                        v = getattr(t, attr, None)
                        try:
                            cal = v() if callable(v) else v
                            if cal is not None and hasattr(cal,'empty') and not cal.empty:
                                break
                        except Exception:
                            continue
                    if cal is not None and hasattr(cal,'to_dict'):
                        dct = cal.to_dict()
                        flat_vals = []
                        for k, vs in dct.items():
                            if isinstance(vs, dict):
                                vs = list(vs.values())
                            for v in (vs or []):
                                flat_vals.append(v)
                        for v in flat_vals:
                            try:
                                ts = pd.to_datetime(v, errors='coerce')
                                if ts is not None and ts is not pd.NaT:
                                    dd = ts.date()
                                    if dd >= today and dd <= end_date:
                                        future_date = dd
                                        break
                            except Exception:
                                continue
                if future_date:
                    # Fetch company short name best-effort
                    short_name = None
                    try:
                        info = getattr(t, 'info', {}) if hasattr(t, 'info') else {}
                        if isinstance(info, dict):
                            short_name = info.get('shortName') or info.get('longName')
                    except Exception:
                        short_name = None
                    items.append(UpcomingEarningsItem(symbol=sym, name=short_name, earnings_date=str(future_date), session=None))
            except Exception:
                continue
        items.sort(key=lambda x: x.earnings_date or '')
    else:
        # HK/CN not implemented yet -> return empty
        items = []
    return UpcomingEarningsResponse(market=market, count=len(items), items=items)
