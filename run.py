#!/usr/bin/env python3
"""后端启动器。

这是**人**和**打包产物**共用的入口：

    python run.py                      # 默认 127.0.0.1:8000
    python run.py --port 8001
    python run.py --reload             # 开发时热重载

为什么不让大家直接敲 `uvicorn backend.main:app`：那条命令没有任何东西阻止
`--host 0.0.0.0`。而 `backend/main.py` 的模块文档已经写明，一旦绑到 0.0.0.0，
同局域网内任何人都能读你的行情缓存、并透过 `/llm/chat` 烧掉你的 API 额度。
把这条约定写进代码里（`_guard_host`），比写在注释里求人遵守可靠得多。

Tauri 打包时也以这个文件为 sidecar 入口，所以打包后的应用同样受这条约束。
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import sys
from pathlib import Path

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000

#: 明确要求监听所有网卡时才允许的非回环地址。
LOOPBACK_NAMES = {"localhost", "localhost.localdomain"}


def _is_loopback(host: str) -> bool:
    if host in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _guard_host(host: str, allow_remote: bool) -> str:
    """拒绝把服务暴露到回环之外，除非显式要求。"""
    if _is_loopback(host):
        return host
    if allow_remote:
        print(
            f"警告：正在监听 {host}，同网段的任何设备都能访问本服务，"
            "包括你的行情缓存与 /llm/chat（会消耗你的 API 额度）。",
            file=sys.stderr,
        )
        return host
    raise SystemExit(
        f"拒绝绑定到 {host}：本服务只应监听回环地址。\n"
        "同网段内任何人都能访问你的行情缓存，并透过 /llm/chat 消耗你的 API 额度。\n"
        "确实需要对外暴露时，显式加上 --allow-remote。"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="启动 Stock MCPilot 后端（默认只监听 127.0.0.1）。",
    )
    parser.add_argument("--host", default=os.getenv("SMP_BIND_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(os.getenv("SMP_BIND_PORT", DEFAULT_PORT)))
    parser.add_argument(
        "--reload",
        action="store_true",
        help="改动代码后自动重启（仅开发用；会多起一个监视进程）",
    )
    parser.add_argument("--log-level", default="info")
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="允许绑定非回环地址。除非你清楚后果，否则不要用。",
    )
    args = parser.parse_args(argv)

    host = _guard_host(args.host, args.allow_remote)

    # 打包成 sidecar 后，工作目录不一定是项目根，所以显式把项目根放进 sys.path，
    # 保证 `backend.main` 能被 import。
    root = Path(__file__).resolve().parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    import uvicorn

    # 显式导入一次，别删。
    #
    # uvicorn 是用**字符串**（"backend.main:app"）去 import 应用的，PyInstaller
    # 的静态分析看不到这种导入。少了这一行，打包出来的 sidecar 能启动、能跑
    # bootloader，然后在加载应用那一刻报 `No module named 'backend'` —— 而这时候
    # 已经是用户双击图标的时候了。多写一行 import，让打包器看得见。
    import backend.main  # noqa: F401

    uvicorn.run(
        "backend.main:app",
        host=host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
