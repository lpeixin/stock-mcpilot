"""股票代码与市场之间的换算。

原实现把这段映射逻辑散落在三个地方（``storage/cache.py``、``routers/stocks.py``
的 ``_company_name`` 与 ``get_stock_earnings``），彼此还有细微不一致。这里收敛成
唯一来源。
"""

from __future__ import annotations

MARKETS = ("US", "HK", "CN")

_SUFFIX_TO_MARKET = {
    ".HK": "HK",
    ".SS": "CN",
    ".SZ": "CN",
    ".BJ": "CN",
}


def strip_suffix(symbol: str) -> str:
    """去掉交易所后缀，返回纯代码。``0700.HK`` → ``0700``。"""
    text = (symbol or "").strip().upper()
    for suffix in _SUFFIX_TO_MARKET:
        if text.endswith(suffix):
            return text[: -len(suffix)]
    return text


def infer_market(symbol: str) -> str | None:
    """从带后缀的代码推断市场。无后缀时返回 None。"""
    text = (symbol or "").strip().upper()
    for suffix, market in _SUFFIX_TO_MARKET.items():
        if text.endswith(suffix):
            return market
    return None


def normalize_hk_code(code: str) -> str:
    """港股代码统一成 Yahoo 的 4 位形式。

    用户可能输入 ``700`` / ``0700`` / ``00700``，Yahoo 只认 ``0700.HK``。
    """
    digits = "".join(ch for ch in code if ch.isdigit())
    if not digits:
        return code
    if len(digits) <= 4:
        return digits.zfill(4)
    return digits


def to_yf_symbol(symbol: str, market: str) -> str:
    """本地代码 + 市场 → yfinance 代码。

    >>> to_yf_symbol("700", "HK")
    '0700.HK'
    >>> to_yf_symbol("600519", "CN")
    '600519.SS'
    """
    code = strip_suffix(symbol)
    market = (market or "US").upper()

    if market == "HK":
        return f"{normalize_hk_code(code)}.HK"
    if market == "CN":
        digits = "".join(ch for ch in code if ch.isdigit())
        if digits.startswith("6") or digits.startswith("9"):
            return f"{digits}.SS"
        if digits.startswith(("0", "3")):
            return f"{digits}.SZ"
        if digits.startswith(("4", "8")):
            # 北交所
            return f"{digits}.BJ"
        return f"{digits}.SS"
    return code


def market_currency(market: str) -> str:
    return {"US": "USD", "HK": "HKD", "CN": "CNY"}.get((market or "").upper(), "")


def market_timezone(market: str) -> str:
    return {
        "US": "America/New_York",
        "HK": "Asia/Hong_Kong",
        "CN": "Asia/Shanghai",
    }.get((market or "").upper(), "America/New_York")
