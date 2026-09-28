"""技术指标计算。

全部为纯 pandas/numpy 实现，不依赖 TA-Lib，保证在任何机器上结果一致、可复现、
可单元测试。所有对外返回值都转换成原生 Python 类型（``float`` / ``None``），
避免 numpy 标量泄漏到 JSON 序列化层。

约定
----
- MACD 柱（``hist``）采用国内行情软件口径 ``2 × (DIF − DEA)``。
- RSI 与 ATR 使用 Wilder 平滑（``ewm(alpha=1/period)``），与主流软件一致。
- 数据不足时返回 ``None`` 而不是 0 —— 把"算不出来"和"算出来是 0"区分开。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------

def _clean(value) -> float | None:
    """numpy/pandas 标量 → 原生 float；NaN/Inf → None。"""
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(result):
        return None
    return result


def _column(df: pd.DataFrame, *names: str) -> pd.Series | None:
    """按候选名取列，兼容大小写（yfinance 有时返回 ``Close``，缓存里是 ``close``）。"""
    lowered = {str(c).lower(): c for c in df.columns}
    for name in names:
        actual = lowered.get(name.lower())
        if actual is not None:
            return pd.to_numeric(df[actual], errors="coerce")
    return None


# --------------------------------------------------------------------------
# 单项指标
# --------------------------------------------------------------------------

def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=window).mean()


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def wilder_smooth(series: pd.Series, period: int) -> pd.Series:
    """Wilder 平滑（又称 RMA）。

    与 ``ewm(alpha=1/period, adjust=False)`` 的**唯一但关键**的差别在种子：
    Wilder 用前 ``period`` 个有效值的简单平均作为起点，而 ``ewm`` 默认把第一个值
    当作起点。对 RSI / ATR 这类指标，两种口径在序列开头能差出十几个点，必须按
    Wilder 的原始定义实现，否则与行情软件对不上。
    """
    values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    size = len(values)
    out = np.full(size, np.nan)
    if size == 0:
        return pd.Series(out, index=series.index)

    valid = np.where(np.isfinite(values))[0]
    if len(valid) < period:
        return pd.Series(out, index=series.index)

    seed_slice = valid[:period]
    seed_pos = int(seed_slice[-1])
    previous = float(np.mean(values[seed_slice]))
    out[seed_pos] = previous

    for index in range(seed_pos + 1, size):
        current = values[index]
        if not np.isfinite(current):
            out[index] = previous
            continue
        previous = (previous * (period - 1) + current) / period
        out[index] = previous

    return pd.Series(out, index=series.index)


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder RSI。

    首个有效读数出现在索引 ``period``（需要 period 个价格变动），此后递推。
    """
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    avg_gain = wilder_smooth(gain, period)
    avg_loss = wilder_smooth(loss, period)

    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    result = 100.0 - (100.0 / (1.0 + rs))
    # 全程无下跌时 avg_loss 为 0，RS 变成 inf，此时 RSI 应为 100。
    result = result.where(avg_loss != 0.0, 100.0)
    # 窗口内价格完全没动过（涨跌均为 0）时没有有效读数，保持 NaN。
    result = result.where((avg_gain != 0.0) | (avg_loss != 0.0), np.nan)
    return result


def macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """返回 ``dif`` / ``dea`` / ``hist``（hist 为国内口径的 2 倍柱）。"""
    dif = ema(close, fast) - ema(close, slow)
    dea = dif.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = (dif - dea) * 2.0
    return pd.DataFrame({"dif": dif, "dea": dea, "hist": hist})


def bollinger(close: pd.Series, window: int = 20, num_std: float = 2.0) -> pd.DataFrame:
    mid = sma(close, window)
    std = close.rolling(window=window, min_periods=window).std(ddof=0)
    upper = mid + num_std * std
    lower = mid - num_std * std
    span = (upper - lower).replace(0.0, np.nan)
    pct_b = (close - lower) / span
    bandwidth = span / mid.replace(0.0, np.nan)
    return pd.DataFrame(
        {"mid": mid, "upper": upper, "lower": lower, "pct_b": pct_b, "bandwidth": bandwidth}
    )


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """真实波幅 TR = max(H−L, |H−C_prev|, |L−C_prev|)。

    首根 K 线没有前收盘价，TR **无定义**，显式置为 NaN。注意 ``max(axis=1)`` 默认
    会跳过 NaN，若不显式屏蔽，首根的 TR 会退化成 ``H−L`` 并混进 Wilder 种子，
    导致整条 ATR 序列错位一根。
    """
    prev_close = close.shift(1)
    ranges = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    )
    return ranges.max(axis=1).where(prev_close.notna())


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder ATR：对真实波幅做 Wilder 平滑。"""
    return wilder_smooth(true_range(high, low, close), period)


def kdj(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    n: int = 9,
    m1: int = 3,
    m2: int = 3,
) -> pd.DataFrame:
    lowest = low.rolling(window=n, min_periods=n).min()
    highest = high.rolling(window=n, min_periods=n).max()
    span = (highest - lowest).replace(0.0, np.nan)
    rsv = (close - lowest) / span * 100.0
    rsv = rsv.fillna(50.0).where(highest.notna(), np.nan)
    k = rsv.ewm(alpha=1.0 / m1, adjust=False, min_periods=1).mean()
    d = k.ewm(alpha=1.0 / m2, adjust=False, min_periods=1).mean()
    j = 3.0 * k - 2.0 * d
    return pd.DataFrame({"k": k, "d": d, "j": j})


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff().fillna(0.0))
    return (direction * volume.fillna(0.0)).cumsum()


def volume_ratio(volume: pd.Series, window: int = 5) -> pd.Series:
    """量比：当日成交量 / 近 N 日均量。"""
    baseline = volume.rolling(window=window, min_periods=window).mean()
    return volume / baseline.replace(0.0, np.nan)


# --------------------------------------------------------------------------
# 组合计算
# --------------------------------------------------------------------------

DEFAULT_WINDOWS = (5, 10, 20, 60)


def compute_frame(df: pd.DataFrame, ma_windows: tuple[int, ...] = DEFAULT_WINDOWS) -> pd.DataFrame:
    """给 OHLCV 数据帧追加全部指标列。返回新对象，不修改入参。"""
    if df is None or df.empty:
        return pd.DataFrame()

    close = _column(df, "close")
    high = _column(df, "high")
    low = _column(df, "low")
    volume = _column(df, "volume")
    if close is None or high is None or low is None:
        return df.copy()

    out = df.copy()
    for window in ma_windows:
        out[f"ma{window}"] = sma(close, window)

    out["rsi14"] = rsi(close, 14)

    macd_frame = macd(close)
    out["macd_dif"] = macd_frame["dif"]
    out["macd_dea"] = macd_frame["dea"]
    out["macd_hist"] = macd_frame["hist"]

    boll = bollinger(close)
    out["boll_mid"] = boll["mid"]
    out["boll_upper"] = boll["upper"]
    out["boll_lower"] = boll["lower"]
    out["boll_pct_b"] = boll["pct_b"]

    out["atr14"] = atr(high, low, close, 14)

    kdj_frame = kdj(high, low, close)
    out["kdj_k"] = kdj_frame["k"]
    out["kdj_d"] = kdj_frame["d"]
    out["kdj_j"] = kdj_frame["j"]

    if volume is not None:
        out["obv"] = obv(close, volume)
        out["vol_ma5"] = sma(volume, 5)
        out["volume_ratio"] = volume_ratio(volume, 5)
    else:
        out["obv"] = np.nan
        out["vol_ma5"] = np.nan
        out["volume_ratio"] = np.nan

    # 单日涨跌幅与振幅
    out["pct_change"] = close.pct_change() * 100.0
    prev_close = close.shift(1)
    out["amplitude"] = (high - low) / prev_close.replace(0.0, np.nan) * 100.0

    return out


def latest_snapshot(df: pd.DataFrame) -> dict:
    """取最后一根 K 线上的指标值，供上下文注入与前端展示使用。"""
    if df is None or df.empty:
        return {}

    row = df.iloc[-1]

    def pick(name: str) -> float | None:
        return _clean(row[name]) if name in df.columns else None

    close = pick("close")
    atr_value = pick("atr14")
    snapshot: dict = {
        "close": close,
        "pct_change": pick("pct_change"),
        "ma": {f"ma{w}": pick(f"ma{w}") for w in DEFAULT_WINDOWS},
        "rsi14": pick("rsi14"),
        "macd": {
            "dif": pick("macd_dif"),
            "dea": pick("macd_dea"),
            "hist": pick("macd_hist"),
        },
        "boll": {
            "upper": pick("boll_upper"),
            "mid": pick("boll_mid"),
            "lower": pick("boll_lower"),
            "pct_b": pick("boll_pct_b"),
        },
        "atr14": atr_value,
        "atr_pct": (atr_value / close * 100.0) if (atr_value and close) else None,
        "kdj": {"k": pick("kdj_k"), "d": pick("kdj_d"), "j": pick("kdj_j")},
        "volume_ratio": pick("volume_ratio"),
        "amplitude": pick("amplitude"),
    }
    return snapshot


def derive_signals_structured(snapshot: dict) -> list[dict]:
    """把指标数值翻译成**机器可读**的观察项。

    返回 ``[{"code": str, "params": dict}, ...]``。

    为什么要多这一层：中文界面直接渲染文本即可，但英文界面需要自己组句。
    如果只返回中文句子，英文 UI 里就会混进中文。让后端给"编码 + 参数"、
    前端负责措辞，两边共用同一份判断逻辑，不会分叉。

    这里只做**机械的、可复现的**描述（"收盘价在 20 日均线上方"），不做预测性
    判断 —— 判断留给模型，但结论必须基于这些客观事实。
    """
    signals: list[dict] = []
    close = snapshot.get("close")
    ma = snapshot.get("ma") or {}

    for window in ("ma20", "ma60"):
        level = ma.get(window)
        if close and level:
            signals.append(
                {
                    "code": "ma_relation",
                    "params": {
                        "ma": window.upper(),
                        "side": "above" if close > level else "below",
                        "close": float(close),
                        "ma_value": float(level),
                    },
                }
            )

    ma5, ma10, ma20 = ma.get("ma5"), ma.get("ma10"), ma.get("ma20")
    if ma5 and ma10 and ma20:
        if ma5 > ma10 > ma20:
            mode = "bull"
        elif ma5 < ma10 < ma20:
            mode = "bear"
        else:
            mode = "mixed"
        signals.append({"code": "ma_alignment", "params": {"mode": mode}})

    rsi_value = snapshot.get("rsi14")
    if rsi_value is not None:
        if rsi_value >= 70:
            zone = "overbought"
        elif rsi_value <= 30:
            zone = "oversold"
        else:
            zone = "neutral"
        signals.append(
            {"code": "rsi_zone", "params": {"value": float(rsi_value), "zone": zone}}
        )

    macd = snapshot.get("macd") or {}
    dif, dea, hist = macd.get("dif"), macd.get("dea"), macd.get("hist")
    if dif is not None and dea is not None:
        signals.append(
            {"code": "macd_cross", "params": {"mode": "golden" if dif > dea else "dead"}}
        )
        if hist is not None and dif > 0 and dea > 0:
            signals.append({"code": "macd_axis", "params": {"side": "above"}})
        elif hist is not None and dif < 0 and dea < 0:
            signals.append({"code": "macd_axis", "params": {"side": "below"}})

    boll = snapshot.get("boll") or {}
    pct_b = boll.get("pct_b")
    if pct_b is not None:
        if pct_b > 1:
            mode = "above_upper"
        elif pct_b < 0:
            mode = "below_lower"
        elif pct_b > 0.8:
            mode = "near_upper"
        elif pct_b < 0.2:
            mode = "near_lower"
        else:
            mode = None
        if mode:
            signals.append({"code": "boll_zone", "params": {"mode": mode}})

    kdj = snapshot.get("kdj") or {}
    k, d = kdj.get("k"), kdj.get("d")
    if k is not None and d is not None:
        if k > d and k < 80:
            signals.append(
                {"code": "kdj_cross", "params": {"mode": "golden", "k": float(k), "d": float(d)}}
            )
        elif k < d and k > 20:
            signals.append(
                {"code": "kdj_cross", "params": {"mode": "dead", "k": float(k), "d": float(d)}}
            )

    ratio = snapshot.get("volume_ratio")
    if ratio is not None:
        if ratio >= 1.5:
            mode = "heavy"
        elif ratio <= 0.6:
            mode = "light"
        else:
            mode = "normal"
        signals.append({"code": "volume_ratio", "params": {"value": float(ratio), "mode": mode}})

    atr_pct = snapshot.get("atr_pct")
    if atr_pct is not None:
        signals.append({"code": "atr_scale", "params": {"value": float(atr_pct)}})

    return signals


def _render_zh_signal(item: dict) -> str | None:
    """把一条结构化判读渲染成中文句子（供 AI 上下文与中文界面使用）。"""
    code = item.get("code")
    p = item.get("params") or {}

    if code == "ma_relation":
        side = "上方" if p.get("side") == "above" else "下方"
        return f"收盘价位于 {p.get('ma')} {side}（{p.get('close', 0):.2f} vs {p.get('ma_value', 0):.2f}）"
    if code == "ma_alignment":
        return {
            "bull": "均线多头排列（MA5 > MA10 > MA20）",
            "bear": "均线空头排列（MA5 < MA10 < MA20）",
            "mixed": "均线交织，趋势不明确",
        }.get(p.get("mode"))
    if code == "rsi_zone":
        return {
            "overbought": f"RSI14 为 {p.get('value', 0):.1f}，进入超买区间（≥70）",
            "oversold": f"RSI14 为 {p.get('value', 0):.1f}，进入超卖区间（≤30）",
            "neutral": f"RSI14 为 {p.get('value', 0):.1f}，处于中性区间",
        }.get(p.get("zone"))
    if code == "macd_cross":
        return "MACD 的 DIF 位于 DEA 上方（金叉状态）" if p.get("mode") == "golden" else "MACD 的 DIF 位于 DEA 下方（死叉状态）"
    if code == "macd_axis":
        return "MACD 位于零轴上方" if p.get("side") == "above" else "MACD 位于零轴下方"
    if code == "boll_zone":
        return {
            "above_upper": "价格突破布林带上轨",
            "below_lower": "价格跌破布林带下轨",
            "near_upper": "价格贴近布林带上轨",
            "near_lower": "价格贴近布林带下轨",
        }.get(p.get("mode"))
    if code == "kdj_cross":
        label = "金叉" if p.get("mode") == "golden" else "死叉"
        return f"KDJ {label}（K={p.get('k', 0):.1f}, D={p.get('d', 0):.1f}）"
    if code == "volume_ratio":
        return {
            "heavy": f"量比 {p.get('value', 0):.2f}，成交明显放量",
            "light": f"量比 {p.get('value', 0):.2f}，成交明显缩量",
            "normal": f"量比 {p.get('value', 0):.2f}，成交量与近期均值接近",
        }.get(p.get("mode"))
    if code == "atr_scale":
        return f"ATR14 占价格 {p.get('value', 0):.2f}%，可作为日内波动的参考尺度"
    return None


def derive_signals(snapshot: dict) -> list[str]:
    """结构化判读的中文渲染（AI 上下文与中文界面共用）。"""
    out: list[str] = []
    for item in derive_signals_structured(snapshot):
        text = _render_zh_signal(item)
        if text:
            out.append(text)
    return out


def compute_summary(df: pd.DataFrame) -> dict:
    """区间统计摘要（替代原 ``StockAnalysisSummary``，指标更完整）。"""
    if df is None or df.empty:
        return {}

    close = _column(df, "close")
    volume = _column(df, "volume")
    if close is None:
        return {}

    close = close.dropna()
    if close.empty:
        return {}

    returns = close.pct_change().dropna()
    running_max = close.cummax()
    drawdown = close / running_max - 1.0

    summary: dict = {
        "count": int(len(close)),
        "start_date": str(pd.to_datetime(df.index[0]).date()),
        "end_date": str(pd.to_datetime(df.index[-1]).date()),
        "first_close": _clean(close.iloc[0]),
        "last_close": _clean(close.iloc[-1]),
        "mean_close": _clean(close.mean()),
        "high": _clean(close.max()),
        "low": _clean(close.min()),
        "return_pct": _clean((close.iloc[-1] / close.iloc[0] - 1.0) * 100.0),
        "max_drawdown_pct": _clean(drawdown.min() * 100.0),
        "volatility_pct": _clean(returns.std(ddof=1) * 100.0) if len(returns) > 1 else None,
        "annualized_volatility_pct": (
            _clean(returns.std(ddof=1) * np.sqrt(252) * 100.0) if len(returns) > 1 else None
        ),
        "max_single_day_gain_pct": _clean(returns.max() * 100.0) if len(returns) else None,
        "max_single_day_loss_pct": _clean(returns.min() * 100.0) if len(returns) else None,
        "up_days": int((returns > 0).sum()),
        "down_days": int((returns < 0).sum()),
    }

    if volume is not None:
        volume = volume.dropna()
        if not volume.empty:
            summary["vol_mean"] = _clean(volume.mean())
            summary["vol_last"] = _clean(volume.iloc[-1])

    # 与前期区间对比，给出"近期 vs 全区间"的动能差
    if len(close) >= 40:
        recent = close.tail(20)
        prior = close.tail(40).head(20)
        recent_return = (recent.iloc[-1] / recent.iloc[0] - 1.0) * 100.0
        prior_return = (prior.iloc[-1] / prior.iloc[0] - 1.0) * 100.0
        summary["recent_20d_return_pct"] = _clean(recent_return)
        summary["prior_20d_return_pct"] = _clean(prior_return)
        summary["momentum_acceleration_pct"] = _clean(recent_return - prior_return)

    return summary
