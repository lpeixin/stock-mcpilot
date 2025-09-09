from datetime import date, datetime, time, timedelta
import pandas as pd
from .db import load_prices, upsert_prices

def _market_symbol(symbol: str, market: str) -> str:
    if market == "HK" and not symbol.endswith(".HK"):
        return symbol + ".HK"
    if market == "CN":
        # Simplified suffix mapping (could use akshare for exact exchange)
        if symbol.startswith("6"):
            return symbol + ".SS"
        else:
            return symbol + ".SZ"
    return symbol

def fetch_remote(symbol: str, market: str, start, end) -> pd.DataFrame:
    yf_symbol = _market_symbol(symbol, market)
    import yfinance as yf
    df = yf.download(yf_symbol, start=start, end=end, auto_adjust=False, progress=False)
    if df.empty:
        return df
    # 处理可能出现的 MultiIndex (单股票某些场景或未来扩展多股票导致)
    if isinstance(df.columns, pd.MultiIndex):
        new_cols = []
        for col in df.columns:  # col is a tuple
            parts = [str(x) for x in col if x is not None and str(x) != '' ]
            # 去掉冗余的 ticker 部分
            parts_filtered = [p for p in parts if p.upper() not in {symbol.upper(), yf_symbol.upper()}]
            if not parts_filtered:
                parts_filtered = parts[-1:]
            new_cols.append('_'.join(parts_filtered))
        df.columns = new_cols
    # 统一转为小写并替换空格
    rename_map = {}
    for c in df.columns:
        base = c
        if isinstance(base, tuple):
            base = '_'.join(str(x) for x in base)
        rename_map[c] = str(base).replace(' ', '_').lower()
    df = df.rename(columns=rename_map)
    df.index = pd.to_datetime(df.index)
    df['symbol'] = symbol
    df['market'] = market
    return df

def get_price_data(symbol: str, market: str, start: date, end: date) -> pd.DataFrame:
    cached_rows = load_prices(symbol, market, start, end)
    if cached_rows:
        df_cached = pd.DataFrame(cached_rows)
        df_cached.set_index(pd.to_datetime(df_cached['date']), inplace=True)
        df_cached = df_cached.sort_index()
    else:
        df_cached = pd.DataFrame()
    need_fetch = True
    if not df_cached.empty:
        # naive gap detection
        days = (end - start).days + 1
        if len(df_cached) > days * 0.5:  # have >50% days -> still try fetch to fill
            need_fetch = True
    if need_fetch:
        # yfinance 的 end 是非包含（右开）区间；为了确保包含“今天”尚在交易或刚收盘的日线，向后加一天
        fetch_end = end + timedelta(days=1)
        remote = fetch_remote(symbol, market, start, fetch_end)
        if not remote.empty:
            to_upsert = []
            for idx, row in remote.iterrows():
                to_upsert.append({
                    'symbol': symbol,
                    'market': market,
                    'date': idx.date(),
                    'open': float(row.get('open', 0)),
                    'high': float(row.get('high', 0)),
                    'low': float(row.get('low', 0)),
                    'close': float(row.get('close', 0)),
                    'volume': int(row.get('volume', 0)),
                })
            upsert_prices(to_upsert)
            cached_rows = load_prices(symbol, market, start, end)
            df_cached = pd.DataFrame(cached_rows)
            if not df_cached.empty:
                df_cached.set_index(pd.to_datetime(df_cached['date']), inplace=True)
    return df_cached

# ---------------- Intraday (current day) support -----------------
from zoneinfo import ZoneInfo
import yfinance as yf

_MARKET_TZ = {
    'US': 'America/New_York',
    'HK': 'Asia/Hong_Kong',
    'CN': 'Asia/Shanghai'
}

def _session_status(market: str):
    """Return ('pre'|'open'|'closed', today_date_in_tz). Very rough, ignores holidays."""
    tzname = _MARKET_TZ.get(market.upper(), 'America/New_York')
    now = datetime.now(ZoneInfo(tzname))
    today = now.date()
    weekday = now.weekday()  # 0=Mon
    if weekday >= 5:
        return 'closed', today
    # Define sessions
    if market.upper() == 'US':
        open_t, close_t = time(9,30), time(16,0)
        if now.time() < open_t:
            return 'pre', today
        if now.time() >= close_t:
            return 'closed', today
        return 'open', today
    if market.upper() == 'HK':
        # Simplified two sessions: 09:30-12:00, 13:00-16:00
        t = now.time()
        if t < time(9,30):
            return 'pre', today
        if time(9,30) <= t < time(12,0) or time(13,0) <= t < time(16,0):
            return 'open', today
        if t < time(16,0):
            return 'closed', today  # lunch treated as closed (no updates)
        return 'closed', today
    if market.upper() == 'CN':
        # CN: 09:30-11:30, 13:00-15:00
        t = now.time()
        if t < time(9,30):
            return 'pre', today
        if time(9,30) <= t < time(11,30) or time(13,0) <= t < time(15,0):
            return 'open', today
        if t < time(15,0):
            return 'closed', today
        return 'closed', today
    # default: treat like US
    open_t, close_t = time(9,30), time(16,0)
    if now.time() < open_t:
        return 'pre', today
    if now.time() >= close_t:
        return 'closed', today
    return 'open', today

def _fetch_live_price(symbol: str, market: str):
    """Fetch current (intraday) price using yfinance. Returns dict or None."""
    try:
        yf_symbol = _market_symbol(symbol, market)
        t = yf.Ticker(yf_symbol)
        fast = getattr(t, 'fast_info', {}) or {}
        # yfinance fast_info may be attribute-like or dict-like
        def _fast_get(k):
            if isinstance(fast, dict):
                return fast.get(k)
            return getattr(fast, k, None)
        price = _fast_get('last_price') or _fast_get('lastPrice') or _fast_get('last_trade') or _fast_get('lastTrade')
        day_open = _fast_get('open')
        day_high = _fast_get('day_high') or _fast_get('dayHigh') or _fast_get('high')
        day_low = _fast_get('day_low') or _fast_get('dayLow') or _fast_get('low')
        vol = _fast_get('last_volume') or _fast_get('volume')
        if price is None:
            hist = t.history(period="1d", interval="1m")
            if not hist.empty:
                last_row = hist.tail(1).iloc[0]
                price = float(last_row['Close'])
                if day_open is None:
                    day_open = float(hist['Open'].iloc[0])
                if day_high is None:
                    day_high = float(hist['High'].max())
                if day_low is None:
                    day_low = float(hist['Low'].min())
                if vol is None and 'Volume' in hist.columns:
                    vol = int(hist['Volume'].sum())
        if price is None:
            return None
        # fallback fill
        if day_open is None: day_open = price
        if day_high is None: day_high = max(day_open, price)
        if day_low is None: day_low = min(day_open, price)
        if vol is None: vol = 0
        return {
            'open': float(day_open),
            'high': float(day_high),
            'low': float(day_low),
            'close': float(price),
            'volume': int(vol)
        }
    except Exception:
        return None

def maybe_update_intraday(symbol: str, market: str):
    """Ensure today's row exists & updated.

    - 在开市时间: 使用实时价格刷新当日行。
    - 在收盘后(且本地还没有当日行): 用历史数据/实时最后价补写收盘行。
    返回更新后的行或 None。
    """
    status, today = _session_status(market)
    existing_rows = load_prices(symbol, market, today, today)

    # 市场开市 -> 实时刷新
    if status == 'open':
        live = _fetch_live_price(symbol, market)
        if not live:
            return None
        if existing_rows:
            row = existing_rows[0]
            row['high'] = float(max(row.get('high') or live['high'], live['high']))
            row['low'] = float(min(row.get('low') or live['low'], live['low']))
            row['close'] = float(live['close'])
            if not row.get('open'):
                row['open'] = float(live['open'])
            row['volume'] = int(live.get('volume') or row.get('volume') or 0)
            upsert_prices([row])
            return row
        new_row = {
            'symbol': symbol,
            'market': market,
            'date': today,
            **live
        }
        upsert_prices([new_row])
        return new_row

    # 收盘后还没有当日行 -> 尝试用日线数据补
    if status == 'closed' and not existing_rows:
        try:
            yf_symbol = _market_symbol(symbol, market)
            t = yf.Ticker(yf_symbol)
            hist = t.history(period="2d")
            if not hist.empty:
                last = hist.tail(1)
                idx_date = last.index[-1].date()
                if idx_date == today:
                    r = last.iloc[0]
                    row = {
                        'symbol': symbol,
                        'market': market,
                        'date': today,
                        'open': float(r.get('Open', r.get('open', 0) or 0)),
                        'high': float(r.get('High', r.get('high', 0) or 0)),
                        'low': float(r.get('Low', r.get('low', 0) or 0)),
                        'close': float(r.get('Close', r.get('close', 0) or 0)),
                        'volume': int(r.get('Volume', r.get('volume', 0) or 0)),
                    }
                    upsert_prices([row])
                    return row
        except Exception:
            return None
    return None

