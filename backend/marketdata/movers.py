"""涨跌榜与财报日历。

涨跌榜改用 ``yf.screen`` + ``EquityQuery``：用区域条件筛选，再由服务端按涨跌幅
排序。相比改造前那套"手工拼 Yahoo screener URL + 事后过滤"的做法，优点是三地
市场统一、排序由服务端完成、且不必自己处理符号后缀过滤。

财报日历没有对应的批量接口，只能在标的池上并发查询。改造前是 41 个标的串行
``yf.Ticker().get_earnings_dates()``，一次要几十秒；这里改为线程池并发 + 结果缓存。
"""

from __future__ import annotations

import concurrent.futures
import threading
import time

import yfinance as yf

from .symbols import strip_suffix
from .yf_client import _int, _num, _text

# 区域代码（Yahoo 的口径）
_REGION = {"US": "us", "HK": "hk", "CN": "cn"}

# 榜单过滤门槛：太小的票没有参考价值，也容易是脏数据
_MIN_VOLUME = {"US": 500_000, "HK": 300_000, "CN": 1_000_000}
_MIN_MARKET_CAP = {"US": 300_000_000, "HK": 200_000_000, "CN": 500_000_000}

# 覆盖度优先的标的池（各市场权重股 + 活跃中概/热门股）。
# 财报日历是在这个池子上逐个查询的，所以池子越大命中越多 —— 但也要控制规模，
# 否则首次查询会明显变慢（结果会缓存 30 分钟）。
_UNIVERSE = {
    "US": [
        # 科技
        "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "TSLA", "AVGO", "ORCL", "AMD",
        "NFLX", "CRM", "ADBE", "INTC", "QCOM", "CSCO", "TXN", "MU", "AMAT", "LRCX",
        "NOW", "INTU", "IBM", "UBER", "SHOP", "SNOW", "PLTR", "PANW", "ANET", "KLAC",
        # 金融
        "JPM", "BAC", "WFC", "GS", "MS", "V", "MA", "AXP", "BLK", "SCHW",
        "C", "USB", "PNC", "TFC", "COF", "BK", "SPGI", "MMC", "CB", "PGR",
        # 能源与材料
        "XOM", "CVX", "COP", "SLB", "OXY", "EOG", "PSX", "MPC", "VLO", "LIN",
        # 医药
        "JNJ", "PFE", "MRK", "ABBV", "LLY", "UNH", "TMO", "ABT", "AMGN", "GILD",
        "BMY", "CVS", "CI", "ELV", "MDT", "ISRG", "VRTX", "REGN", "ZTS", "SYK",
        # 消费与零售
        "WMT", "COST", "HD", "NKE", "MCD", "SBUX", "PG", "KO", "PEP", "DIS",
        "TGT", "LOW", "TJX", "BKNG", "CMG", "MDLZ", "CL", "MO", "PM", "KHC",
        # 工业与公用
        "BA", "CAT", "GE", "HON", "UPS", "LMT", "RTX", "DE", "MMM", "UNP",
        "NEE", "DUK", "SO", "AEP", "EXC",
        # 中概
        "PDD", "BABA", "JD", "NIO", "XPEV", "LI", "BIDU", "TCOM", "NTES", "BILI",
        "TME", "IQ", "VIPS", "YUMC", "ZTO",
    ],
    "HK": [
        "0700.HK", "9988.HK", "3690.HK", "0941.HK", "1299.HK", "0388.HK", "0005.HK",
        "1810.HK", "9618.HK", "9888.HK", "2318.HK", "1398.HK", "3988.HK", "0939.HK",
        "2628.HK", "0386.HK", "0857.HK", "0883.HK", "0001.HK", "0016.HK", "0011.HK",
        "2382.HK", "1093.HK", "2269.HK", "1177.HK", "6098.HK", "2020.HK", "2331.HK",
        "6690.HK", "1024.HK", "2015.HK", "9866.HK", "9868.HK", "9626.HK", "0992.HK",
        "1928.HK", "0027.HK", "0175.HK", "1211.HK", "2333.HK", "0981.HK", "6618.HK",
        "0268.HK", "0288.HK", "0322.HK", "2319.HK", "1044.HK", "0151.HK", "0762.HK",
        "0688.HK", "1109.HK", "0012.HK", "0017.HK", "0083.HK", "0960.HK", "1918.HK",
        "2007.HK", "3383.HK", "3993.HK", "1772.HK", "1378.HK", "3323.HK", "0914.HK",
    ],
    "CN": [
        "600519.SS", "601318.SS", "600036.SS", "601166.SS", "600030.SS", "601888.SS",
        "600900.SS", "601899.SS", "600276.SS", "603288.SS", "600887.SS", "601012.SS",
        "688981.SS", "688111.SS", "600809.SS", "601088.SS", "600028.SS", "601857.SS",
        "601398.SS", "601288.SS", "601988.SS", "601939.SS", "600016.SS", "601328.SS",
        "600000.SS", "601601.SS", "601628.SS", "601336.SS", "600104.SS", "601633.SS",
        "600585.SS", "600031.SS", "601668.SS", "601390.SS", "601186.SS", "600050.SS",
        "603259.SS", "600438.SS", "601225.SS", "600690.SS", "600309.SS", "600760.SS",
        "000001.SZ", "000002.SZ", "000333.SZ", "000651.SZ", "000858.SZ", "002594.SZ",
        "002415.SZ", "002714.SZ", "300750.SZ", "300059.SZ", "300124.SZ", "002352.SZ",
        "002475.SZ", "300760.SZ", "002304.SZ", "000725.SZ", "000568.SZ", "002027.SZ",
        "002142.SZ", "000063.SZ", "002230.SZ", "300015.SZ", "300274.SZ", "002460.SZ",
    ],
}


# --------------------------------------------------------------------------
# 涨跌榜
# --------------------------------------------------------------------------

def _to_item(quote: dict, market: str) -> dict | None:
    symbol = _text(quote.get("symbol"))
    if not symbol:
        return None
    return {
        "symbol": strip_suffix(symbol),
        "yf_symbol": symbol,
        "market": market,
        "name": _text(quote.get("shortName")) or _text(quote.get("longName")),
        "price": _num(quote.get("regularMarketPrice")),
        "change": _num(quote.get("regularMarketChange")),
        "change_pct": _num(quote.get("regularMarketChangePercent")),
        "volume": _int(quote.get("regularMarketVolume")),
        "market_cap": _num(quote.get("marketCap")),
        "currency": _text(quote.get("currency")),
        "exchange": _text(quote.get("exchange")),
    }


def get_movers(market: str, kind: str = "gainers", count: int = 10) -> list[dict]:
    """取指定市场的涨幅榜或跌幅榜。失败返回空列表。"""
    market = (market or "US").upper()
    region = _REGION.get(market, "us")
    ascending = kind == "losers"

    try:
        from yfinance import EquityQuery
    except ImportError:  # pragma: no cover
        return []

    try:
        query = EquityQuery(
            "and",
            [
                EquityQuery("eq", ["region", region]),
                EquityQuery("gt", ["dayvolume", _MIN_VOLUME.get(market, 500_000)]),
                EquityQuery("gt", ["intradaymarketcap", _MIN_MARKET_CAP.get(market, 300_000_000)]),
            ]
        )
        # 多取一些再按符号后缀过滤，避免被其他市场的票挤占名额
        result = yf.screen(
            query,
            size=min(max(count * 4, 40), 250),
            sortField="percentchange",
            sortAsc=ascending,
        )
    except Exception:  # noqa: BLE001
        return []

    quotes = (result or {}).get("quotes") or []
    items: list[dict] = []
    for quote in quotes:
        item = _to_item(quote, market)
        if item is None:
            continue
        change_pct = item["change_pct"]
        if change_pct is None:
            continue
        # 符号方向过滤：榜单里偶尔混进反向的票
        if ascending and change_pct >= 0:
            continue
        if not ascending and change_pct <= 0:
            continue
        if not _symbol_matches_market(item["yf_symbol"], market):
            continue
        items.append(item)

    items.sort(key=lambda entry: entry["change_pct"] or 0.0, reverse=not ascending)
    return items[:count]


def _symbol_matches_market(yf_symbol: str, market: str) -> bool:
    upper = (yf_symbol or "").upper()
    if market == "HK":
        return upper.endswith(".HK")
    if market == "CN":
        return upper.endswith((".SS", ".SZ", ".BJ"))
    return not upper.endswith((".HK", ".SS", ".SZ", ".BJ"))


# --------------------------------------------------------------------------
# 财报日历
# --------------------------------------------------------------------------

_earnings_cache: dict[str, tuple[float, list[dict]]] = {}
_earnings_lock = threading.Lock()
_EARNINGS_TTL = 1800.0


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _as_date(value):
    """把 yfinance 可能返回的各种时间表示统一成 ``datetime.date``。"""
    from datetime import date, datetime

    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:  # pandas.Timestamp / numpy.datetime64
        return value.date()  # type: ignore[union-attr]
    except AttributeError:
        pass
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.strptime(text[:10], "%Y-%m-%d").date()
        except ValueError:
            return None


def _fetch_earnings_date(yf_symbol: str) -> dict | None:
    """查一个标的的下一个财报日。取不到就返回 None（不猜日期）。"""
    from datetime import date

    today = date.today()
    try:
        ticker = yf.Ticker(yf_symbol)
    except Exception:  # noqa: BLE001
        return None

    # 顺序很重要：先查 calendarEvents。
    # 它一次请求就能给出"下次财报日"（含尚未发生的），而 get_earnings_dates 在
    # 两次财报之间的窗口里常常只返回历史日期 —— 改造前把顺序写反了，于是每次都要
    # 多打一次请求，命中率还更低。
    calendar: dict = {}
    try:
        raw_calendar = ticker.calendar
        if isinstance(raw_calendar, dict):
            calendar = raw_calendar
    except Exception:  # noqa: BLE001
        calendar = {}

    candidates = [
        stamp
        for stamp in (_as_date(value) for value in _as_list(calendar.get("Earnings Date")))
        if stamp and stamp >= today
    ]

    # 兜底：极少数标的 calendar 为空，但历史日历里带着未来日期。
    if not candidates:
        try:
            frame = ticker.get_earnings_dates(limit=8)
            if frame is not None and not frame.empty:
                candidates = [
                    stamp
                    for stamp in (_as_date(index) for index in frame.index)
                    if stamp and stamp >= today
                ]
        except Exception:  # noqa: BLE001
            pass

    if not candidates:
        return None

    next_date = min(candidates)

    # 确认有财报日之后才取 info。它对绝大多数标的都是纯浪费（一个完整
    # quoteSummary 请求），放在前面会让整个扫描慢好几倍。
    info: dict = {}
    try:
        raw_info = getattr(ticker, "info", None)
        if isinstance(raw_info, dict):
            info = raw_info
    except Exception:  # noqa: BLE001
        info = {}

    return {
        "symbol": strip_suffix(yf_symbol),
        "yf_symbol": yf_symbol,
        "name": _text(info.get("shortName")) or _text(info.get("longName")),
        "earnings_date": str(next_date),
        "days_until": (next_date - today).days,
        # calendar 里的是"下个季度的一致预期"，比 forwardEps（未来 12 个月）更贴合这一期
        "eps_estimate": _num(calendar.get("Earnings Average")) or _num(info.get("forwardEps")),
        "market_cap": _num(info.get("marketCap")),
        "currency": _text(info.get("currency")),
    }


def get_upcoming_earnings(market: str = "US", days: int = 14, limit: int = 50) -> list[dict]:
    """取未来 ``days`` 天内的财报安排。结果缓存 30 分钟。"""
    from datetime import date, timedelta

    market = (market or "US").upper()
    key = market

    now = time.time()
    with _earnings_lock:
        cached = _earnings_cache.get(key)
        if cached and now - cached[0] < _EARNINGS_TTL:
            horizon = date.today() + timedelta(days=days)
            return [
                item
                for item in cached[1]
                if item["earnings_date"] <= str(horizon)
            ][:limit]

    universe = _UNIVERSE.get(market) or []
    if not universe:
        return []

    collected: list[dict] = []
    # 并发查询：串行跑上百个标的要几十秒，并发后通常 5~10 秒（结果缓存 30 分钟）。
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        for item in pool.map(_fetch_earnings_date, universe):
            if item:
                collected.append(item)

    collected.sort(key=lambda entry: entry["earnings_date"])

    with _earnings_lock:
        _earnings_cache[key] = (now, collected)

    horizon = date.today() + timedelta(days=days)
    return [item for item in collected if item["earnings_date"] <= str(horizon)][:limit]
