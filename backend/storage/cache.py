"""行情数据获取与本地缓存。

日线走"本地缓存 + 增量补齐"：只在缓存缺口处联网，而不是每次都全量重拉。
周线/月线由日线重采样得到，避免额外请求；分钟线量小、时效性强，直接实时拉取。

修复记录
--------
改造前 ``maybe_update_intraday`` 末尾的 ``return new_row`` 缩进在函数体层级，
导致市场状态为 ``pre`` / ``closed`` 时直接抛 ``NameError``，被上层
``except Exception: pass`` 静默吞掉——README 里承诺的"收盘后用官方收盘价覆盖盘中
缓存"因此从未生效，其后的 25 行也全是死代码。这里重写为显式的分支返回。
"""

from __future__ import annotations

import time
from datetime import date, datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

from ..marketdata.symbols import market_timezone, to_yf_symbol
from .db import (
    earliest_price_date,
    latest_price_date,
    load_prices,
    upsert_prices,
)

# --------------------------------------------------------------------------
# 市场状态
# --------------------------------------------------------------------------

#: 各市场的交易时段（本地时间）。未考虑节假日，节假日由"当天是否拿到数据"兜底判断。
_SESSIONS: dict[str, tuple[tuple[dtime, dtime], ...]] = {
    "US": ((dtime(9, 30), dtime(16, 0)),),
    "HK": ((dtime(9, 30), dtime(12, 0)), (dtime(13, 0), dtime(16, 0))),
    "CN": ((dtime(9, 30), dtime(11, 30)), (dtime(13, 0), dtime(15, 0))),
}

#: 各周期允许的最大回溯天数（yfinance 的硬限制）
_INTERVAL_MAX_DAYS = {
    "1m": 7,
    "2m": 59,
    "5m": 59,
    "15m": 59,
    "30m": 59,
    "60m": 729,
    "90m": 59,
    "1h": 729,
}

_PERIOD_DAYS = {
    "1d": 1,
    "5d": 5,
    "1mo": 31,
    "3mo": 92,
    "6mo": 183,
    "1y": 366,
    "2y": 731,
    "5y": 1827,
    "10y": 3653,
    "ytd": None,
    "max": None,
}


def market_session(market: str) -> dict:
    """返回市场当前交易状态。

    ``status`` 取值：``pre``（盘前）、``open``（交易中）、``lunch``（午休）、
    ``closed``（已收盘或休市）。
    """
    market = (market or "US").upper()
    timezone = ZoneInfo(market_timezone(market))
    now = datetime.now(timezone)
    today = now.date()
    current = now.time()

    if now.weekday() >= 5:
        return {"status": "closed", "date": today, "timezone": str(timezone), "now": now.isoformat()}

    sessions = _SESSIONS.get(market, _SESSIONS["US"])
    first_open = sessions[0][0]
    last_close = sessions[-1][1]

    if current < first_open:
        status = "pre"
    elif current >= last_close:
        status = "closed"
    else:
        status = "lunch"
        for start, end in sessions:
            if start <= current < end:
                status = "open"
                break

    return {"status": status, "date": today, "timezone": str(timezone), "now": now.isoformat()}


def is_market_open(market: str) -> bool:
    return market_session(market)["status"] == "open"


# --------------------------------------------------------------------------
# 远程拉取
# --------------------------------------------------------------------------

def _normalize_frame(df: pd.DataFrame, symbol: str, market: str) -> pd.DataFrame:
    """把 yfinance 的返回整理成统一的小写列 + 日期索引。"""
    if df is None or df.empty:
        return pd.DataFrame()

    # 单标的也可能返回 MultiIndex 列（yfinance 的行为随版本变化）
    if isinstance(df.columns, pd.MultiIndex):
        flattened: list[str] = []
        for column in df.columns:
            parts = [str(part) for part in column if part not in (None, "")]
            parts = [p for p in parts if p.upper() not in {symbol.upper(), to_yf_symbol(symbol, market).upper()}]
            flattened.append("_".join(parts or [str(column[-1])]))
        df = df.copy()
        df.columns = flattened

    rename = {column: str(column).replace(" ", "_").lower() for column in df.columns}
    df = df.rename(columns=rename)

    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    df = df[~df.index.isna()]
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df


def fetch_remote_daily(symbol: str, market: str, start: date, end: date) -> pd.DataFrame:
    """从 yfinance 拉取日线。``end`` 按左闭右开处理，调用方无需自己 +1 天。"""
    yf_symbol = to_yf_symbol(symbol, market)
    try:
        frame = yf.download(
            yf_symbol,
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,
        )
    except Exception:  # noqa: BLE001
        return pd.DataFrame()
    return _normalize_frame(frame, symbol, market)


def fetch_remote_intraday(symbol: str, market: str, interval: str, period: str) -> pd.DataFrame:
    yf_symbol = to_yf_symbol(symbol, market)
    try:
        frame = yf.download(
            yf_symbol,
            period=period,
            interval=interval,
            auto_adjust=False,
            progress=False,
            threads=False,
        )
    except Exception:  # noqa: BLE001
        return pd.DataFrame()
    return _normalize_frame(frame, symbol, market)


def _rows_from_frame(frame: pd.DataFrame, symbol: str, market: str) -> list[dict]:
    rows: list[dict] = []
    for index, row in frame.iterrows():
        close = row.get("close")
        if close is None or pd.isna(close):
            continue
        rows.append(
            {
                "symbol": symbol,
                "market": market,
                "date": pd.to_datetime(index).date(),
                "open": _to_float(row.get("open")),
                "high": _to_float(row.get("high")),
                "low": _to_float(row.get("low")),
                "close": _to_float(close),
                "volume": _to_int(row.get("volume")),
            }
        )
    return rows


def _to_float(value) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if result != result else result


def _to_int(value) -> int | None:
    result = _to_float(value)
    return None if result is None else int(result)


# --------------------------------------------------------------------------
# 日线缓存
# --------------------------------------------------------------------------

def get_price_data(
    symbol: str,
    market: str,
    start: date,
    end: date,
    *,
    allow_fetch: bool = True,
) -> pd.DataFrame:
    """获取日线（优先本地缓存，只补齐缺口）。

    返回的 DataFrame 以日期为索引、小写列为字段，可直接交给指标模块。
    """
    cached = _load_cached_frame(symbol, market, start, end)

    if allow_fetch:
        cached = _fill_gaps(symbol, market, start, end, cached)

    if cached.empty:
        return cached
    return cached


def _load_cached_frame(symbol: str, market: str, start: date, end: date) -> pd.DataFrame:
    rows = load_prices(symbol, market, start, end)
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.set_index("date").sort_index()
    frame = frame.drop(columns=["symbol", "market"], errors="ignore")
    for column in ("open", "high", "low", "close", "volume"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


#: 记录"某个区间确实没有数据"（例如标的上市之前），避免每次请求都白跑一趟网络。
_empty_ranges: dict[tuple[str, str], set[tuple[date, date]]] = {}


def _remember_empty(symbol: str, market: str, start: date, end: date) -> None:
    _empty_ranges.setdefault((symbol, market), set()).add((start, end))


def _is_known_empty(symbol: str, market: str, start: date, end: date) -> bool:
    return (start, end) in _empty_ranges.get((symbol, market), set())


def _fetch_and_store(symbol: str, market: str, start: date, end: date) -> int:
    """拉取并落库，返回写入行数。"""
    if end < start:
        return 0
    frame = fetch_remote_daily(symbol, market, start, end)
    rows = _rows_from_frame(frame, symbol, market)
    if rows:
        upsert_prices(rows)
    else:
        _remember_empty(symbol, market, start, end)
    return len(rows)


def _fill_gaps(
    symbol: str,
    market: str,
    start: date,
    end: date,
    cached: pd.DataFrame,
) -> pd.DataFrame:
    """只补齐缺失区段，并对**内部空洞**做自愈。

    改造前只检查区间两端，因此一旦中间有一段没拉到（限流、源站抖动、进程被杀），
    那个空洞就永久留在缓存里，指标随之失真。这里额外用"工作日数量"做一次完整性
    估算：实际行数明显少于工作日数就整段重拉。
    """
    if cached.empty:
        _fetch_and_store(symbol, market, start, end)
        return _load_cached_frame(symbol, market, start, end)

    first_cached = cached.index.min().date()
    last_cached = cached.index.max().date()

    # 向后补齐
    if last_cached < end and not _is_known_empty(symbol, market, last_cached, end):
        _fetch_and_store(symbol, market, last_cached, end)

    # 向前补齐（标的上市之前永远拿不到，用负缓存避免重复请求）
    if first_cached > start and not _is_known_empty(symbol, market, start, first_cached):
        _fetch_and_store(symbol, market, start, first_cached)

    current = _load_cached_frame(symbol, market, start, end)
    if current.empty:
        return current

    # 内部空洞自愈
    span_start = current.index.min().date()
    span_end = current.index.max().date()
    expected_weekdays = int(np.busday_count(span_start, span_end + timedelta(days=1)))
    if expected_weekdays > 0 and len(current) < expected_weekdays * 0.85:
        if not _is_known_empty(symbol, market, span_start, span_end):
            _fetch_and_store(symbol, market, span_start, span_end)
            current = _load_cached_frame(symbol, market, start, end)

    return current


def ensure_history(symbol: str, market: str, days: int) -> pd.DataFrame:
    """保证本地至少有近 ``days`` 个自然日的数据，返回该区间的日线。"""
    end = date.today()
    start = end - timedelta(days=days)
    return get_price_data(symbol, market, start, end)


# --------------------------------------------------------------------------
# K 线（多周期）
# --------------------------------------------------------------------------

def _resample_daily(frame: pd.DataFrame, rule: str) -> pd.DataFrame:
    if frame.empty:
        return frame
    aggregated = frame.resample(rule).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    return aggregated.dropna(subset=["close"])


#: 各周期的指标暖机天数。周线/月线的 MA60 需要 60 根周/月线，
#: 换算成自然日分别约 550 天 / 2200 天，否则图上开头的长周期均线会一片空。
_WARMUP_DAYS = {"1d": 400, "1wk": 550, "1mo": 2200}


def get_candles(
    symbol: str,
    market: str,
    *,
    period: str = "6mo",
    interval: str = "1d",
    with_indicators: bool = True,
) -> tuple[pd.DataFrame, str]:
    """获取指定周期与频率的 K 线。

    返回 ``(数据帧, 实际使用的频率)``。

    指标在**目标周期上**计算，而不是在日线上算完再降采样 —— 后者的周线 MA 其实
    是"每周最后一天的日线 MA"，含义是错的。因此顺序是：先按目标频率重采样，
    再算指标，最后裁到请求区间。
    """
    from ..analysis import indicators as ind

    interval = (interval or "1d").lower()
    period = (period or "6mo").lower()

    # --- 分钟线：实时拉取，不算指标（分钟级指标意义有限且数据量小）---
    if interval in _INTERVAL_MAX_DAYS:
        max_days = _INTERVAL_MAX_DAYS[interval]
        requested_days = _PERIOD_DAYS.get(period)
        if requested_days is not None and requested_days > max_days:
            # 超出该频率可回溯范围，降级成日线而不是返回空
            interval = "1d"
        else:
            frame = fetch_remote_intraday(symbol, market, interval, period)
            if not frame.empty:
                return frame, interval
            interval = "1d"

    # --- 日线及以上 ---
    if period == "max":
        days = 3650 * 4
    elif period == "ytd":
        days = (date.today() - date(date.today().year, 1, 1)).days + 5
    else:
        days = _PERIOD_DAYS.get(period) or 183

    warmup = _WARMUP_DAYS.get(interval, 400)
    start = date.today() - timedelta(days=days + warmup)
    frame = get_price_data(symbol, market, start, date.today())
    if frame.empty:
        return frame, interval

    if interval == "1wk":
        frame = _resample_daily(frame, "W-FRI")
    elif interval == "1mo":
        frame = _resample_daily(frame, "ME")

    if with_indicators:
        frame = ind.compute_frame(frame)

    cutoff = pd.Timestamp(date.today() - timedelta(days=days))
    sliced = frame.loc[frame.index >= cutoff]
    return (sliced if not sliced.empty else frame), interval


# --------------------------------------------------------------------------
# 盘中更新
# --------------------------------------------------------------------------

def _fetch_live_snapshot(symbol: str, market: str) -> dict | None:
    """用 fast_info / 分钟线拼出当日快照。"""
    yf_symbol = to_yf_symbol(symbol, market)
    try:
        ticker = yf.Ticker(yf_symbol)
    except Exception:  # noqa: BLE001
        return None

    price = open_price = day_high = day_low = volume = None
    try:
        fast = ticker.fast_info
        price = _to_float(_fast_get(fast, "lastPrice"))
        open_price = _to_float(_fast_get(fast, "open"))
        day_high = _to_float(_fast_get(fast, "dayHigh"))
        day_low = _to_float(_fast_get(fast, "dayLow"))
        volume = _to_int(_fast_get(fast, "lastVolume"))
    except Exception:  # noqa: BLE001
        pass

    if price is None:
        try:
            history = ticker.history(period="1d", interval="1m")
            if not history.empty:
                price = _to_float(history["Close"].iloc[-1])
                open_price = open_price or _to_float(history["Open"].iloc[0])
                day_high = day_high or _to_float(history["High"].max())
                day_low = day_low or _to_float(history["Low"].min())
                volume = volume or _to_int(history["Volume"].sum())
        except Exception:  # noqa: BLE001
            pass

    if price is None:
        return None

    open_price = open_price or price
    return {
        "open": open_price,
        "high": day_high or max(open_price, price),
        "low": day_low or min(open_price, price),
        "close": price,
        "volume": volume or 0,
    }


def _fast_get(fast, key: str):
    if fast is None:
        return None
    if hasattr(fast, "get"):
        try:
            value = fast.get(key)
            if value is not None:
                return value
        except Exception:  # noqa: BLE001
            pass
    return getattr(fast, key, None)


def _fetch_daily_row(symbol: str, market: str, target: date) -> dict | None:
    """从日线里取指定日期的那一根。"""
    frame = fetch_remote_daily(symbol, market, target - timedelta(days=5), target)
    if frame.empty:
        return None
    for index in reversed(frame.index):
        if pd.to_datetime(index).date() == target:
            row = frame.loc[index]
            close = _to_float(row.get("close"))
            if close is None:
                return None
            return {
                "symbol": symbol,
                "market": market,
                "date": target,
                "open": _to_float(row.get("open")),
                "high": _to_float(row.get("high")),
                "low": _to_float(row.get("low")),
                "close": close,
                "volume": _to_int(row.get("volume")),
            }
    return None


def maybe_update_intraday(symbol: str, market: str) -> dict | None:
    """确保当日那根 K 线存在且尽量新鲜。

    - 交易中：用实时快照刷新（最高/最低取累计值，而不是覆盖）
    - 收盘后：若本地还没有当日行，用官方日线补上
    - 盘前 / 午休：不动数据
    """
    session = market_session(market)
    status = session["status"]
    today = session["date"]
    existing = load_prices(symbol, market, today, today)

    if status == "open":
        live = _fetch_live_snapshot(symbol, market)
        if live is None:
            return None

        if existing:
            row = dict(existing[0])
            row["high"] = max(_to_float(row.get("high")) or live["high"], live["high"])
            row["low"] = min(_to_float(row.get("low")) or live["low"], live["low"])
            row["close"] = live["close"]
            if not row.get("open"):
                row["open"] = live["open"]
            row["volume"] = live.get("volume") or row.get("volume") or 0
            upsert_prices([row])
            return row

        new_row = {"symbol": symbol, "market": market, "date": today, **live}
        upsert_prices([new_row])
        return new_row

    # 收盘后补当日收盘；盘前与午休无需动作。
    if status == "closed" and not existing:
        row = _fetch_daily_row(symbol, market, today)
        if row:
            upsert_prices([row])
            return row

    return None


# --------------------------------------------------------------------------
# 便捷入口
# --------------------------------------------------------------------------

def get_price_frame_with_indicators(symbol: str, market: str, days: int) -> pd.DataFrame:
    """取带全部技术指标的日线。供路由与 AI 上下文共用。

    指标需要暖机数据（MA60、ATR14 等都要足够的前置样本），因此先多取约 400 天
    算指标，再裁回请求区间 —— 否则区间开头的 MA60 会是一片空值。
    """
    from ..analysis import indicators as ind

    warmup_start = date.today() - timedelta(days=days + 400)
    extended = get_price_data(symbol, market, warmup_start, date.today())
    if extended.empty:
        return extended

    computed = ind.compute_frame(extended)
    cutoff = pd.Timestamp(date.today() - timedelta(days=days))
    sliced = computed.loc[computed.index >= cutoff]
    return sliced if not sliced.empty else computed


def wait_for_rate_limit(seconds: float = 0.2) -> None:
    """给密集调用之间留一点间隔，降低被 Yahoo 限流的概率。"""
    time.sleep(seconds)
