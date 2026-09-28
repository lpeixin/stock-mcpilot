"""端到端验证：起后端 + 静态服务 + 无头 Chrome，断言界面真的渲染出来，并截图。

为什么用一个脚本而不是几条命令：本环境的沙箱会在两次工具调用之间回收后台进程，
所以服务、浏览器、断言必须活在同一个进程生命周期里。

跑法::

    .venv/bin/python scripts/verify_ui.py
    SMP_SHOT_DIR=docs/screenshots .venv/bin/python scripts/verify_ui.py   # 顺便产出 README 截图

关于配置目录：脚本把 ``STOCK_MCPILOT_HOME`` 指向临时目录（真实配置会被复制过去），
所以既不会改写你自己的 API Key 配置，截图内容也可复现。
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import httpx
from websockets.asyncio.client import connect

ROOT = Path(__file__).resolve().parent.parent


def _venv_python() -> str:
    """项目 venv 里的解释器。找不到就退回当前解释器。

    这里以前写死了一个绝对路径（某台机器上 .workbuddy-ai 里的 Python），
    既是**本机路径泄漏**（会随代码一起推到 GitHub），也让别人 clone 下来必挂。
    """
    for candidate in (ROOT / ".venv" / "bin" / "python", ROOT / ".venv" / "Scripts" / "python.exe"):
        if candidate.exists():
            return str(candidate)
    return sys.executable


#: 跑后端用项目 venv 的解释器；静态文件服务用当前解释器就够了。
VENV_PY = _venv_python()
STATIC_PY = sys.executable

#: 无头 Chrome 的位置。非 macOS 或用非默认安装位置时用 SMP_CHROME 覆盖。
CHROME = os.getenv("SMP_CHROME") or "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROFILE = Path(os.getenv("SMP_CHROME_PROFILE") or "/tmp/smp-chrome-profile")
#: 截图输出目录。指向 docs/screenshots 时产出的就是 README 用的那批图，
#: 这样"文档里的截图"天然来自一次通过的验证，不会和代码脱节。
OUT = Path(os.getenv("SMP_SHOT_DIR") or "/tmp/smp-shots")

#: 界面语言。中英文各跑一遍，英文那份用来给英文 README 配图 ——
#: 顺带把英文界面也纳入验证：在此之前它从来没被端到端跑过，
#: 缺翻译、i18n key 漏了都发现不了。
UI_LANG = (os.getenv("SMP_UI_LANG") or "zh").strip().lower()
if UI_LANG not in ("zh", "en"):
    UI_LANG = "zh"

#: 断言要用到的界面文案。必须与 frontend/src/i18n/index.ts 一致 ——
#: 这里刻意写死而不是从 i18n 文件里解析：脚本要能发现"文案被改了"，
#: 跟着自动变就永远发现不了。
TEXTS: dict[str, dict[str, object]] = {
    "zh": {
        "nav": {"home": "个股", "movers": "涨跌榜", "upcoming": "财报日历", "settings": "设置"},
        "cards": ["技术指标", "关键指标", "公司概况", "AI 分析", "近期新闻"],
        "ai_card": "AI 分析",
        "model_card": "模型服务",
        "zoom_in": "放大",
        "reset_zoom": "重置缩放",
        "visible_prefix": "当前可见",
        "backend_error": "无法连接后端",
    },
    "en": {
        "nav": {"home": "Stock", "movers": "Movers", "upcoming": "Earnings", "settings": "Settings"},
        "cards": [
            "Technical indicators",
            "Key metrics",
            "Company profile",
            "AI analysis",
            "Recent news",
        ],
        "ai_card": "AI analysis",
        "model_card": "Model service",
        "zoom_in": "Zoom in",
        "reset_zoom": "Reset zoom",
        "visible_prefix": "Visible",
        "backend_error": "Cannot reach the backend",
    },
}
T = TEXTS[UI_LANG]

#: 截图用的配置目录（见 make_isolated_home 的说明）。
SHOT_CONFIG_HOME = Path(os.getenv("SMP_SHOT_CONFIG_HOME") or "/tmp/stock-mcpilot-demo")

#: 截图用的代表性配置。
#:
#: 刻意**不**复制开发者本人的配置：
#:   1. 这些图会进 README、进公开仓库，不能夹带任何真实凭据
#:      （设置页会把密钥渲染成 sk-1****cdef，前后 4 位也是真密钥的一部分）；
#:   2. 每次跑出来的图必须一致，不能随个人配置漂移；
#:   3. "已配置好一个模型"比"未配置模型"的红色警告更适合做产品截图。
SCREENSHOT_CONFIG: dict = {
    "version": 1,
    "llm": {
        "preset": "ollama",
        "kind": "ollama",
        "base_url": "http://127.0.0.1:11434",
        "model": "qwen3.5:9b",
        "api_key": "",
    },
    "ui": {"language": UI_LANG},
    "analysis": {"language": UI_LANG},
}

BACKEND_PORT = 8000
STATIC_PORT = 4173
CDP_PORT = 9222

# 127.0.0.1 必须绕开沙箱代理，否则会被代理挡成 502
CLIENT = httpx.Client(trust_env=False, timeout=5.0)


def log(message: str) -> None:
    print(message, flush=True)


def make_isolated_home() -> Path:
    """把后端配置目录指向一个隔离目录，并写入一份**代表性配置**。

    不改动开发者本人的 ``~/.stock-mcpilot/config.json``，也不复制它 ——
    理由见 ``SCREENSHOT_CONFIG`` 上面的注释。

    路径刻意是**固定的、看起来像刻意为之的**，而不是 ``mkdtemp`` 的随机串：
    设置页会把配置路径渲染在界面上（"Stored only on this machine at …"），
    而这些图会进公开仓库 —— ``/var/folders/4_/…/smp-verify-home-kqh9vusw``
    既难看又像是出了 bug。
    """
    home = SHOT_CONFIG_HOME
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.json").write_text(
        json.dumps(SCREENSHOT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return home


def port_open(port: int) -> bool:
    sock = socket.socket()
    sock.settimeout(0.5)
    try:
        sock.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def wait_port(port: int, timeout: float = 40.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_open(port):
            return True
        time.sleep(0.25)
    return False


class CDP:
    def __init__(self, ws) -> None:
        self.ws = ws
        self.next_id = 0

    async def send(self, method: str, params: dict | None = None) -> dict:
        self.next_id += 1
        message_id = self.next_id
        await self.ws.send(
            json.dumps({"id": message_id, "method": method, "params": params or {}})
        )
        while True:
            raw = await asyncio.wait_for(self.ws.recv(), timeout=30)
            payload = json.loads(raw)
            if payload.get("id") == message_id:
                if "error" in payload:
                    raise RuntimeError(f"{method}: {payload['error']}")
                return payload.get("result", {})

    async def evaluate(self, expression: str) -> object:
        result = await self.send(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        outcome = result.get("result", {})
        if result.get("exceptionDetails"):
            raise RuntimeError(result["exceptionDetails"])
        return outcome.get("value")

    async def shot(self, path: Path) -> None:
        result = await self.send("Page.captureScreenshot", {"format": "png"})
        write_png(path, base64.b64decode(result["data"]))


_WARNED_NO_PILLOW = False


def write_png(path: Path, data: bytes) -> None:
    """写 PNG，并顺手压一遍。

    界面截图是大片纯色 + 抗锯齿文字，转成 256 色调色板能砍掉约 65% 体积
    （实测 270 KB → 96 KB），肉眼几乎看不出差别。README 里两个语言版本加起来
    要放十几张图，这一步直接决定了别人 clone 下来的体积。

    调色板化失败时退回原图 —— 压缩是优化，不该让验证挂掉。但**要说一声**：
    静默地不优化，下次看到仓库变大时没人知道该怪谁。
    """
    global _WARNED_NO_PILLOW
    try:
        import io

        from PIL import Image

        image = Image.open(io.BytesIO(data)).convert("RGB")
        buffer = io.BytesIO()
        image.quantize(colors=256, method=Image.MEDIANCUT, dither=Image.NONE).save(
            buffer, format="PNG", optimize=True
        )
        data = buffer.getvalue()
    except Exception:  # noqa: BLE001 - 没有 Pillow 也要能出图
        if not _WARNED_NO_PILLOW:
            _WARNED_NO_PILLOW = True
            log("  提示：未安装 Pillow，截图不做压缩（体积约为压缩后的 3 倍）。")
            log("        装上即可：pip install -r backend/requirements-dev.txt")
    path.write_bytes(data)


def probe_js() -> str:
    """渲染探针。文案随 UI_LANG 变，所以用函数生成而不是常量。"""
    return """
(() => {
  const text = (el) => (el ? el.textContent.trim() : null);
  const canvases = [...document.querySelectorAll('canvas')];
  return {
    heading: text(document.querySelector('h1')),
    price: text(document.querySelector('.text-3xl')),
    canvases: canvases.map((c) => [c.width, c.height]),
    cards: [...document.querySelectorAll('h2')].map((e) => e.textContent.trim()),
    tableRows: document.querySelectorAll('tbody tr').length,
    externalLinks: document.querySelectorAll('a[target="_blank"]').length,
    inputs: document.querySelectorAll('input, textarea').length,
    buttons: document.querySelectorAll('button').length,
    bodyText: document.body.innerText.slice(0, 400),
    errorBanner: document.body.innerText.includes(%(backend_error)s),
    emptyChart: document.body.innerText.includes(%(empty_chart)s),
  };
})()
""" % {
        "backend_error": json.dumps(str(T["backend_error"]), ensure_ascii=False),
        "empty_chart": json.dumps("暂无 K 线数据" if UI_LANG == "zh" else "No candle data",
                                 ensure_ascii=False),
    }


PROBE = probe_js()


#: 本脚本会产出的截图文件名。
#: 清理只针对**不在这份清单里**的 png —— 正常跑一遍一个文件都不用删，
#: 直接覆盖写即可。这样既少了一堆破坏性操作，也避开了受限环境里的删除配额
#: （实测连删 50 个文件就会被安全守卫拦下，而且会连带把整个命令干掉）。
SHOT_FILES = (
    "home.png",
    "chart.png",
    "ai-analysis.png",
    "movers.png",
    "earnings-calendar.png",
    "settings.png",
)


async def run() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    # 只清理"上一次产出过、这一次不再产出"的图（比如截图集合缩小时）。
    for stale in OUT.glob("*.png"):
        if stale.name in SHOT_FILES:
            continue
        try:
            stale.unlink()
        except OSError:
            pass
    if PROFILE.exists():
        shutil.rmtree(PROFILE, ignore_errors=True)

    config_home = make_isolated_home()
    processes: list[subprocess.Popen] = []
    failures: list[str] = []

    # 端口预检：如果端口上已经有一个**别的**进程在监听（比如上一轮跑完没清干净），
    # 新起的 uvicorn 会静默地绑定失败，而 wait_port 照样返回 True —— 结果就是拿着
    # 别人的服务去验证，报出一堆莫名其妙的错。
    #
    # 但要给一段等待窗口：连着跑两种语言（EN 完立刻 ZH）时，上一轮的进程可能还
    # 没完全退出、端口还在 TIME_WAIT。一进来就判定"有残留"会把正常交接误报成故障。
    ports = ((BACKEND_PORT, "后端"), (STATIC_PORT, "静态服务"), (CDP_PORT, "Chrome"))
    deadline = time.time() + 25
    busy = [(port, label) for port, label in ports if port_open(port)]
    while busy and time.time() < deadline:
        time.sleep(0.5)
        busy = [(port, label) for port, label in ports if port_open(port)]
    if busy:
        for port, label in busy:
            log(f"端口 {port}（{label}）已被占用，请先停掉残留进程再跑。")
        return 2

    try:
        log(f"[1/6] 启动后端 …（配置目录：{config_home}）")
        backend_env = dict(os.environ)
        backend_env["STOCK_MCPILOT_HOME"] = str(config_home)
        backend_proc = subprocess.Popen(
            [VENV_PY, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1",
             "--port", str(BACKEND_PORT), "--log-level", "warning"],
            cwd=ROOT,
            env=backend_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        processes.append(backend_proc)
        if not wait_port(BACKEND_PORT):
            log("  后端启动失败")
            return 1
        # wait_port 只能说明"有人在监听"，不能说明**是我们**的后端在监听。
        # 端口被别人占着时 uvicorn 会绑定失败然后立刻退出，而这里依然会返回 True。
        if backend_proc.poll() is not None:
            log(f"  后端进程已退出（退出码 {backend_proc.returncode}）：端口被别的进程占着？")
            return 1
        log(f"  后端就绪 /health -> {CLIENT.get(f'http://127.0.0.1:{BACKEND_PORT}/health').json()['version']}")

        log("[2/6] 启动静态服务（frontend/dist）…")
        static_proc = subprocess.Popen(
            [STATIC_PY, "-m", "http.server", str(STATIC_PORT), "--bind", "127.0.0.1",
             "--directory", str(ROOT / "frontend" / "dist")],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        processes.append(static_proc)
        if not wait_port(STATIC_PORT):
            log("  静态服务启动失败")
            return 1
        if static_proc.poll() is not None:
            log(f"  静态服务进程已退出（退出码 {static_proc.returncode}）：端口被别的进程占着？")
            return 1

        log("[3/6] 启动无头 Chrome …")
        processes.append(
            subprocess.Popen(
                [CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
                 "--no-default-browser-check", "--hide-scrollbars",
                 # 沙箱会设置系统级代理，localhost 也会被绕进去，必须显式直连
                 "--no-proxy-server",
                 # ⚠ 下面这四个不是可选项，删掉脚本会在连 CDP 时随机挂掉。
                 # 本环境是"沙箱里再开沙箱"：Chrome 自己的内部沙箱起不来
                 # （sandbox initialization failed: Operation not permitted），
                 # 于是 GPU 进程反复崩溃，最终
                 # `FATAL: GPU process isn't usable. Goodbye.` 让整个浏览器退出，
                 # 表现为 websockets 报 "no close frame received or sent"。
                 # 只加 --disable-gpu 不够，新版 Chrome 仍会拉起 GPU 进程。
                 "--no-sandbox",
                 "--disable-gpu-sandbox",
                 "--disable-software-rasterizer",
                 "--disable-dev-shm-usage",
                 f"--user-data-dir={PROFILE}",
                 f"--remote-debugging-port={CDP_PORT}",
                 "--window-size=1680,1400", "about:blank"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        )
        if not wait_port(CDP_PORT):
            log("  Chrome 调试端口未就绪")
            return 1

        version = CLIENT.get(f"http://127.0.0.1:{CDP_PORT}/json/version").json()
        log(f"  {version.get('Browser')}")

        # page target 不是 CDP 端口一开就有的（浏览器还要先起渲染进程），
        # 立刻去取可能拿到空列表。等一会儿，别在这里偶发失败。
        page = None
        for _ in range(40):
            targets = CLIENT.get(f"http://127.0.0.1:{CDP_PORT}/json/list").json()
            page = next((item for item in targets if item.get("type") == "page"), None)
            if page and page.get("webSocketDebuggerUrl"):
                break
            page = None
            await asyncio.sleep(0.25)
        if not page:
            log("  没有可用的 page target")
            return 1

        async with connect(page["webSocketDebuggerUrl"], max_size=None) as ws:
            cdp = CDP(ws)
            await cdp.send("Page.enable")
            await cdp.send("Runtime.enable")
            await cdp.send("Log.enable")
            await cdp.send(
                "Emulation.setDeviceMetricsOverride",
                {"width": 1680, "height": 1400, "deviceScaleFactor": 1, "mobile": False},
            )

            log("[4/6] 打开个股页并等待渲染 …")
            await cdp.send("Page.navigate", {"url": f"http://127.0.0.1:{STATIC_PORT}/"})

            probe: dict = {}
            deadline = time.time() + 120
            while time.time() < deadline:
                try:
                    probe = await cdp.evaluate(PROBE) or {}
                except Exception as exc:  # noqa: BLE001
                    probe = {"error": str(exc)}
                # 主数据（报价 + K 线）和次要数据（新闻）都要到位，否则会在
                # loadSecondary 还没回来时就下断言，得到随机的假失败。
                if probe.get("canvases") and probe.get("price") and probe.get("externalLinks"):
                    break
                await asyncio.sleep(1.0)

            log("[5/6] 断言 …")
            checks: list[tuple[str, bool, str]] = []

            # 语言守卫放在最前面。界面语言一旦没生效，后面所有"卡片『Technical
            # indicators』存在"之类的断言都会以看起来毫不相关的方式失败，
            # 让人以为是组件坏了。先在这里把根因点出来。
            nav_texts = await cdp.evaluate(
                "[...document.querySelectorAll('header nav button')].map((b) => b.textContent.trim())"
            )
            expected_nav = list(T["nav"].values())
            checks.append(
                (
                    f"界面语言生效为 {UI_LANG}",
                    nav_texts == expected_nav,
                    f"导航实际为 {nav_texts}，期望 {expected_nav}",
                )
            )

            canvases = probe.get("canvases") or []
            checks.append(("个股标题已渲染", bool(probe.get("heading")), str(probe.get("heading"))))
            checks.append(("报价已渲染", bool(probe.get("price")), str(probe.get("price"))))
            checks.append(
                (
                    "K 线 canvas 已挂载且尺寸合理",
                    bool(canvases) and canvases[0][0] > 400 and canvases[0][1] > 300,
                    str(canvases),
                )
            )
            checks.append(("图表不是空态", not probe.get("emptyChart"), "无『暂无 K 线数据』"))
            cards = probe.get("cards") or []
            for name in T["cards"]:
                checks.append((f"卡片『{name}』存在", name in cards, ", ".join(cards)))
            checks.append(
                ("新闻带原文链接", (probe.get("externalLinks") or 0) > 0, f"{probe.get('externalLinks')} 条")
            )
            checks.append(("没有后端连接错误", not probe.get("errorBanner"), ""))

            # 红涨绿跌是中文用户的既定习惯，也是最容易被改错的一处配色。
            # 直接数 canvas 上的像素，比肉眼看截图可靠。
            palette = await cdp.evaluate(
                """
                (() => {
                  const c = document.querySelector('canvas');
                  if (!c) return null;
                  const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
                  const near = (r, g, b, tr, tg, tb, tol) =>
                    Math.abs(r - tr) < tol && Math.abs(g - tg) < tol && Math.abs(b - tb) < tol;
                  let up = 0, down = 0;
                  for (let i = 0; i < d.length; i += 4) {
                    if (d[i + 3] < 200) continue;
                    if (near(d[i], d[i+1], d[i+2], 217, 63, 76, 30)) up++;
                    else if (near(d[i], d[i+1], d[i+2], 31, 157, 99, 30)) down++;
                  }
                  return { up, down };
                })()
                """
            )
            checks.append(
                (
                    "K 线含红（涨）与绿（跌）两种蜡烛",
                    bool(palette) and palette["up"] > 500 and palette["down"] > 500,
                    f"红 {palette['up'] if palette else 0} px / 绿 {palette['down'] if palette else 0} px",
                )
            )

            await cdp.shot(OUT / "home.png")

            # ---- 缩放是功能，不是"按钮存在" ---------------------------------
            # 图表头部的「当前可见 a ~ b」是组件自己渲染的文本，直接读它：
            # 比去翻 ECharts 内部状态稳，而且它正是用户看得见的东西。
            range_js = (
                "(() => { const el = [...document.querySelectorAll('span')]"
                f".find((s) => s.textContent.trim().startsWith({json.dumps(str(T['visible_prefix']), ensure_ascii=False)}));"
                " return el ? el.textContent.trim() : ''; })()"
            )

            def click_by_title_js(label: str) -> str:
                """按 title 找按钮并点击，**返回是否真的点到了**。

                注意别写成 `[...].find(...)?.click(), true` —— 逗号表达式让整个
                表达式恒为 true，找不到按钮时会静默点空，然后拿上一页的数据去
                断言下一页，失败信息还指向完全错误的方向。
                """
                return (
                    "(() => { const b = [...document.querySelectorAll('button[title]')]"
                    f".find((x) => x.title === {json.dumps(label, ensure_ascii=False)});"
                    " if (!b) return false; b.click(); return true; })()"
                )

            def span_days(text: str) -> int | None:
                """把「当前可见 2026-04-07 ~ 2026-09-25」折算成天数。"""
                found = re.findall(r"\d{4}-\d{2}-\d{2}", text or "")
                if len(found) != 2:
                    return None
                start = date(*map(int, found[0].split("-")))
                end = date(*map(int, found[1].split("-")))
                return (end - start).days

            before_text = await cdp.evaluate(range_js)
            before = span_days(before_text)
            zoomed = await cdp.evaluate(click_by_title_js(str(T["zoom_in"])))
            if not zoomed:
                failures.append(f"找不到『{T['zoom_in']}』按钮")
            await asyncio.sleep(0.8)
            after = span_days(await cdp.evaluate(range_js))
            checks.append(
                (
                    "点『放大』后可见区间真的变窄",
                    before is not None and after is not None and after < before,
                    f"{before} 天 → {after} 天（原文本「{before_text}」）",
                )
            )

            reset_clicked = await cdp.evaluate(click_by_title_js(str(T["reset_zoom"])))
            if not reset_clicked:
                failures.append(f"找不到『{T['reset_zoom']}』按钮")
            await asyncio.sleep(0.8)
            reset = span_days(await cdp.evaluate(range_js))
            checks.append(
                (
                    "点『重置缩放』后可见区间还原",
                    before is not None and reset == before,
                    f"{reset} 天（原始 {before} 天）",
                )
            )

            # 放大截取 K 线图本身，便于人工核对蜡烛、均线颜色与坐标轴标签
            chart_box = await cdp.evaluate(
                "(() => { const c = document.querySelector('canvas');"
                " if (!c) return null; const r = c.getBoundingClientRect();"
                " return { x: Math.round(r.x), y: Math.round(r.y),"
                " width: Math.round(r.width), height: Math.round(r.height), scale: 1 }; })()"
            )
            if chart_box:
                # 2 倍缩放：1x 下每根蜡烛只有几像素，看不出涨跌配色对不对
                result = await cdp.send(
                    "Page.captureScreenshot",
                    {"format": "png", "clip": {**chart_box, "scale": 2}},
                )
                write_png(OUT / "chart.png", base64.b64decode(result["data"]))

            # AI 分析面板单独裁一张：README 里"AI 分析"那一节要有针对性配图，
            # 复用整页截图读者找不到重点。Card 组件渲染成 <section>，用 closest 拿边界。
            ai_box = await cdp.evaluate(
                "(() => {"
                " const h = [...document.querySelectorAll('h2')]"
                f".find((e) => e.textContent.trim() === {json.dumps(str(T['ai_card']), ensure_ascii=False)});"
                " const s = h && h.closest('section');"
                " if (!s) return null;"
                " const r = s.getBoundingClientRect();"
                " if (r.width < 100 || r.height < 100) return null;"
                " return { x: Math.round(r.x), y: Math.round(r.y),"
                " width: Math.round(r.width), height: Math.round(r.height), scale: 2 };"
                " })()"
            )
            if ai_box:
                result = await cdp.send(
                    "Page.captureScreenshot",
                    {"format": "png", "clip": ai_box, "captureBeyondViewport": True},
                )
                write_png(OUT / "ai-analysis.png", base64.b64decode(result["data"]))
            else:
                failures.append("没找到 AI 分析面板，无法裁剪配图")

            # 刻意不再额外产出一张整页长图（1680×3400 那种）。
            # 它在 README 里没有任何引用，却要在仓库里占掉几百 KB × 两个语言版本。
            # 需要看整页时直接滚一遍页面就行，不值得为它付长期体积成本。

            log("[6/6] 切换页面截图 …")
            nav = T["nav"]

            async def goto(label: str, settle: float) -> bool:
                """按可见文案点导航，返回是否真的点到了。

                不用下标：导航项增删时下标会静默错位。也**不要**写成
                `find(...)?.click(), true` —— 逗号表达式恒为 true，点空了也当成功，
                接下来就会拿上一页的数据去断言下一页，失败信息还指向错误方向。
                """
                ok = await cdp.evaluate(
                    "(() => { const b = [...document.querySelectorAll('header nav button')]"
                    f".find((x) => x.textContent.trim() === {json.dumps(label, ensure_ascii=False)});"
                    " if (!b) return false; b.click(); return true; })()"
                )
                if not ok:
                    failures.append(f"找不到导航项『{label}』")
                # 财报日历首次查询要扫描上百个标的（后台预热会覆盖大部分情况）
                await asyncio.sleep(settle)
                return bool(ok)

            for label, filename, settle in (
                (str(nav["movers"]), "movers.png", 6.0),
                (str(nav["upcoming"]), "earnings-calendar.png", 30.0),
            ):
                await goto(label, settle)
                extra = await cdp.evaluate(PROBE) or {}
                await cdp.shot(OUT / filename)
                rows = extra.get("tableRows") or 0
                checks.append((f"『{label}』有数据行", rows > 0, f"{rows} 行"))

            # 设置页只裁「模型服务」卡片，不整页截。
            # 整页截图会把安全区里的配置路径一起拍进去，而跑验证时那个路径是
            # /var/folders/…/smp-verify-home-xxxx —— 公开仓库里的产品截图不该出现
            # 这种东西。服务商分组本来就集中在模型服务卡片里，裁出来更聚焦。
            await goto(str(nav["settings"]), 6.0)
            extra = await cdp.evaluate(PROBE) or {}
            inputs = extra.get("inputs") or 0
            buttons = extra.get("buttons") or 0
            checks.append(
                (
                    "『设置』渲染出表单",
                    inputs >= 5 and buttons >= 12,
                    f"{inputs} 输入框 / {buttons} 按钮",
                )
            )

            # 语言选择器是否与当前语言一致。之前只能靠肉眼看截图，看不清就会
            # 漏掉"界面是英文、语言控件却停在中文"这类不一致。
            lang_pick = await cdp.evaluate(
                "(() => {"
                " const opts = [...document.querySelectorAll('button')]"
                "   .filter((b) => ['简体中文', 'English'].includes(b.textContent.trim()));"
                " const sel = opts.find((b) => b.className.includes('bg-white'));"
                " return { count: opts.length, selected: sel ? sel.textContent.trim() : null };"
                " })()"
            )
            expected_lang_label = "English" if UI_LANG == "en" else "简体中文"
            checks.append(
                (
                    "设置页语言选择器与当前语言一致",
                    isinstance(lang_pick, dict) and lang_pick.get("selected") == expected_lang_label,
                    f"选中 {lang_pick.get('selected') if isinstance(lang_pick, dict) else lang_pick}"
                    f"，期望 {expected_lang_label}",
                )
            )

            settings_box = await cdp.evaluate(
                "(() => {"
                " const h = [...document.querySelectorAll('h2')]"
                f".find((e) => e.textContent.trim() === {json.dumps(str(T['model_card']), ensure_ascii=False)});"
                " const s = h && h.closest('section');"
                " if (!s) return null;"
                " const r = s.getBoundingClientRect();"
                " if (r.width < 200 || r.height < 200) return null;"
                " return { x: Math.round(r.x), y: Math.round(r.y),"
                " width: Math.round(r.width), height: Math.round(r.height), scale: 2 };"
                " })()"
            )
            if settings_box:
                result = await cdp.send(
                    "Page.captureScreenshot",
                    {"format": "png", "clip": settings_box, "captureBeyondViewport": True},
                )
                write_png(OUT / "settings.png", base64.b64decode(result["data"]))
            else:
                failures.append("没找到模型服务卡片，无法裁剪设置页配图")

            # ---- 服务商分组：远程在前、本地在后 -------------------------------
            # 这是需求里点名的一条，所以断言 DOM 里的真实分组结构，
            # 而不是只信后端返回的字典顺序。
            groups = await cdp.evaluate(
                """
                (() => {
                  const box = document.querySelector('[data-provider-groups]');
                  if (!box) return null;
                  return [...box.querySelectorAll('[data-provider-group]')].map((g) => ({
                    key: g.dataset.providerGroup,
                    label: (g.querySelector('div') || {}).textContent?.trim() || '',
                    presets: [...g.querySelectorAll('[data-preset]')].map((b) => b.dataset.preset),
                  }));
                })()
                """
            )
            if not isinstance(groups, list) or not groups:
                failures.append("设置页没有渲染出服务商分组")
                checks.append(("设置页渲染服务商分组", False, str(groups)))
            else:
                keys = [g["key"] for g in groups]
                checks.append(("服务商分为远程与本地两组", keys == ["remote", "local"], str(keys)))
                remote = next((g for g in groups if g["key"] == "remote"), {"presets": []})
                local = next((g for g in groups if g["key"] == "local"), {"presets": []})
                checks.append(
                    (
                        "Anthropic 出现在远程分组里",
                        "anthropic" in remote["presets"],
                        ", ".join(remote["presets"]),
                    )
                )
                checks.append(
                    (
                        "本地分组只含 ollama / lmstudio",
                        sorted(local["presets"]) == ["lmstudio", "ollama"],
                        ", ".join(local["presets"]),
                    )
                )
                # DOM 顺序即视觉顺序：远程组的 DOM 位置必须早于本地组
                checks.append(
                    (
                        "远程分组在本地分组之前（DOM 顺序）",
                        keys.index("remote") < keys.index("local"),
                        f"remote 在 #{keys.index('remote')}，local 在 #{keys.index('local')}",
                    )
                )
                # 分组标题不能是 i18n 的 key 原文（那说明翻译缺失）
                labels = [g["label"] for g in groups]
                checks.append(
                    ("分组标题已本地化", all(lbl and "settings." not in lbl for lbl in labels),
                     " / ".join(labels))
                )

            log("")
            log("=" * 64)
            for name, ok, detail in checks:
                mark = "✓" if ok else "✗"
                log(f"  {mark} {name}" + (f"  ({detail})" if detail else ""))
                if not ok:
                    failures.append(name)
            log("=" * 64)
            log(f"通过 {len(checks) - len(failures)}  失败 {len(failures)}")
            if failures:
                log("失败项：" + "、".join(failures))
            log(f"截图目录：{OUT}")

    finally:
        for process in processes:
            try:
                process.terminate()
            except Exception:  # noqa: BLE001
                pass
        time.sleep(1.0)
        for process in processes:
            try:
                process.kill()
            except Exception:  # noqa: BLE001
                pass
        # 只删自己写进去的那个文件，不 rmtree 整个目录 ——
        # 万一路径被指到了别处，也不至于把别人的东西一起端掉。
        try:
            (config_home / "config.json").unlink()
        except OSError:
            pass

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
