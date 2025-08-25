from datetime import date
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
        remote = fetch_remote(symbol, market, start, end)
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
