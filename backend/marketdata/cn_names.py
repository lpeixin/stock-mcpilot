"""A 股中文简称查询（akshare 可选增强）。

定位：**可选**。核心链路只依赖 yfinance，这个模块只是给 A 股补一个中文名，
让界面比 "KWEICHOW MOUTAI" 更好认。

为什么必须 fail-soft
--------------------
akshare 走的是东方财富等境内站点，在企业代理、境外网络或站点改版时都可能不可用
（本项目的开发沙箱里就是 ``ProxyError``）。因此这里：

  - 延迟导入 akshare（它的 import 本身就要好几秒）
  - 所有调用套在带超时的线程里，避免拖住整个请求
  - 任何异常都吞掉并返回 ``None``，只记一个"不可用"标记
  - 结果缓存一天，且缓存失败结果，避免反复重试

**验证状态**：本模块的失败降级路径已在开发环境验证；成功路径因沙箱网络限制
无法验证，请在能直连东方财富的环境下自行确认。
"""

from __future__ import annotations

import concurrent.futures
import threading
import time

#: 连续失败多少次后就不再尝试（本次进程内）
_MAX_FAILURES = 3
_FAILURE_COOLDOWN = 600.0

_cache: dict[str, tuple[float, str | None]] = {}
_lock = threading.Lock()
_failures = 0
_disabled_until = 0.0
_akshare_module = None
_import_failed = False


def _load_akshare():
    """延迟导入 akshare。导入失败即永久禁用。"""
    global _akshare_module, _import_failed
    if _akshare_module is not None or _import_failed:
        return _akshare_module
    try:
        import akshare  # noqa: PLC0415 - 刻意延迟导入

        _akshare_module = akshare
    except Exception:  # noqa: BLE001
        _import_failed = True
        _akshare_module = None
    return _akshare_module


def _record_failure() -> None:
    global _failures, _disabled_until
    with _lock:
        _failures += 1
        if _failures >= _MAX_FAILURES:
            _disabled_until = time.time() + _FAILURE_COOLDOWN


def available() -> bool:
    """当前是否可以尝试调用 akshare。"""
    if _import_failed:
        return False
    if time.time() < _disabled_until:
        return False
    return _load_akshare() is not None


def status() -> dict:
    return {
        "available": available(),
        "import_ok": not _import_failed,
        "failures": _failures,
        "cooldown_seconds": max(0, int(_disabled_until - time.time())),
        "note": "akshare 为可选增强，不可用时不影响主流程。",
    }


def _lookup_cn_name(code: str, timeout: float = 6.0) -> str | None:
    def work() -> str | None:
        akshare = _load_akshare()
        if akshare is None:
            return None
        frame = akshare.stock_individual_info_em(symbol=code)
        if frame is None or frame.empty:
            return None
        # 返回结构是两列：item / value
        columns = list(frame.columns)
        if len(columns) < 2:
            return None
        item_column, value_column = columns[0], columns[1]
        for _, row in frame.iterrows():
            if str(row[item_column]).strip() in ("股票简称", "简称", "名称"):
                text = str(row[value_column]).strip()
                return text or None
        return None

    # akshare 内部没有超时控制，用线程兜住，避免请求被拖死。
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(work)
        try:
            return future.result(timeout=timeout)
        except Exception:  # noqa: BLE001
            future.cancel()
            return None


def get_cn_name(symbol: str, market: str) -> str | None:
    """取 A 股中文简称。拿不到返回 ``None``。"""
    if (market or "").upper() != "CN":
        return None

    code = "".join(ch for ch in (symbol or "") if ch.isdigit())
    if not code:
        return None

    now = time.time()
    with _lock:
        cached = _cache.get(code)
        if cached and now - cached[0] < 86400:
            return cached[1]

    if not available():
        return None

    try:
        name = _lookup_cn_name(code)
    except Exception:  # noqa: BLE001
        name = None

    if name is None:
        _record_failure()

    with _lock:
        _cache[code] = (now, name)
    return name
