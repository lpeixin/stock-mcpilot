"""FastAPI 应用入口。

安全约定（见 ``config.py`` 的模块文档）：
  - 服务**只应绑定回环地址**。启动脚本（``run.py`` / ``scripts/dev.sh``）已固定
    ``--host 127.0.0.1``，请勿改成 ``0.0.0.0``，否则同局域网内任何人都能访问你的
    行情缓存，并透过 ``/llm/chat`` 消耗你的 API 额度。
  - CORS 只放行本机来源。
  - 明文 API Key 不会出现在任何响应中，对外只有掩码。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import analysis, llm, stocks
from .routers import config as config_routes


def _load_dotenv() -> None:
    """加载项目根目录的 .env（若存在）。

    环境变量的优先级高于配置文件，便于开发与 CI 覆盖；被环境变量锁定的字段会在
    ``/config`` 响应里以 ``locked_by_env`` 标出。
    """
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(env_path, override=False)


_load_dotenv()

APP_VERSION = "0.2.0"

# yfinance 会对"没有财报数据"的标的打一堆 `possibly delisted` 警告。那些标的多数
# 是真实存在、只是 Yahoo 没有其财报日历（港股与 A 股常见）。我们已经用 None 优雅
# 处理了缺失，这些噪声只会淹没真正有用的日志。
logging.getLogger("yfinance").setLevel(logging.ERROR)


def _warm_earnings_calendar() -> None:
    """后台预热三地财报日历缓存。

    首次查询要在上百个标的上逐个请求，约 15 秒。放到后台线程里做，用户点进
    「财报日历」时就是缓存命中（毫秒级）。失败无所谓 —— 前台会自己重试。
    """
    time.sleep(3.0)  # 让服务先把端口和路由准备好
    from .marketdata import movers

    for market in ("US", "HK", "CN"):
        try:
            movers.get_upcoming_earnings(market, days=90, limit=200)
        except Exception:  # noqa: BLE001 - 预热失败不影响服务
            continue


@asynccontextmanager
async def lifespan(_: FastAPI):
    if os.getenv("SMP_NO_WARMUP", "").strip() not in ("1", "true", "yes"):
        threading.Thread(target=_warm_earnings_calendar, daemon=True).start()
    yield


app = FastAPI(
    title="Stock MCPilot API",
    version=APP_VERSION,
    description="本地优先的股票数据分析服务。所有输出仅供研究，不构成投资建议。",
    lifespan=lifespan,
)

# 只允许本机前端访问。
#
# 除了 Tauri 打包后的 tauri:// 来源，其余一律用**正则**放行任意端口的回环地址 ——
# 而不是列举具体端口。原因很实际：开发时换一个端口（`vite --port 4173`）就会让
# 浏览器直接拦下所有响应，前端只能报一句"无法连接后端"，排查起来很费时间。
# 回环地址本身不构成暴露面，所以放宽端口没有安全代价。
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "tauri://localhost",
        "http://tauri.localhost",
    ],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["system"])
def health() -> dict:
    from . import config as app_config

    llm_conf = app_config.resolve_llm()
    return {
        "status": "ok",
        "version": APP_VERSION,
        "host_binding": os.getenv("SMP_BIND_HOST", "127.0.0.1"),
        "llm": {
            "preset": llm_conf.get("preset"),
            "model": llm_conf.get("model"),
            "configured": bool(llm_conf.get("base_url")),
            "api_key_set": bool(llm_conf.get("api_key")),
        },
    }


# 配置：/config 为主，/settings 保留给旧前端。
app.include_router(config_routes.router, prefix="/config", tags=["config"])
app.include_router(config_routes.router, prefix="/settings", tags=["config"], include_in_schema=False)

app.include_router(llm.router, prefix="/llm", tags=["llm"])
app.include_router(stocks.router, prefix="/stocks", tags=["stocks"])
app.include_router(analysis.router, prefix="/analysis", tags=["analysis"])
