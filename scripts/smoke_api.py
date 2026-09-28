"""后端接口冒烟测试。

用法::

    .venv/bin/python scripts/smoke_api.py            # 全量
    .venv/bin/python scripts/smoke_api.py --quick    # 跳过慢用例（涨跌榜/财报日历/LLM）

脚本会自己拉起一个 uvicorn 子进程、等它就绪、跑完所有检查、再关掉它，
因此不依赖外部已经启动的服务。

脚本把 ``STOCK_MCPILOT_HOME`` 指向一个临时目录（真实配置会被复制过去），
所以**不会改动你自己的配置与 API Key**。

关于代理：开发沙箱里 ``HTTP_PROXY`` 会拦截对 127.0.0.1 的请求，所以测试客户端
显式 ``trust_env=False``；而后端自身的出网请求（yfinance）仍走系统代理。
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
HOST = "127.0.0.1"
PORT = int(os.getenv("SMP_SMOKE_PORT", "8011"))

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []
SKIPPED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> bool:
    if condition:
        PASSED.append(name)
        print(f"  \033[32m✓\033[0m {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAILED.append((name, detail))
        print(f"  \033[31m✗\033[0m {name}  {detail}")
    return condition


def skip(name: str, reason: str = "") -> None:
    SKIPPED.append(name)
    print(f"  \033[33m–\033[0m {name}  (跳过{': ' + reason if reason else ''})")


def wait_for_port(host: str, port: int, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.3)
    return False


def make_isolated_home() -> Path:
    """把后端的配置目录指向一个临时目录，返回该目录。

    两个理由，第二个比第一个重要：

    1. 受限沙箱会拒绝写 ``~/.stock-mcpilot/``（原子写用 ``os.replace``，被
       "refused by file policy" 拦下），于是 ``POST /config`` 直接 500 ——
       测到的根本不是业务逻辑。
    2. **原来的写法会改写开发者本人的真实配置**。``POST /config`` 打的是
       ``~/.stock-mcpilot/config.json``，也就是存着真实 API Key 的那个文件；
       测试把它改成 0.42 再改回 0.3，还顺手做了一次原子替换。测试不该动用户的
       真实数据。

    做法是把真实配置**复制**一份到临时目录，之后所有写入都落在副本上。
    复制而不是清空，是为了保住开发者已配好的 base_url / model，
    否则非 quick 模式下的 LLM 推理用例会因为"没选模型"而提前返回。
    """
    home = Path(tempfile.mkdtemp(prefix="smp-smoke-home-"))
    real = Path(os.getenv("STOCK_MCPILOT_HOME") or (Path.home() / ".stock-mcpilot"))
    source = real / "config.json"
    if source.exists():
        try:
            shutil.copy2(source, home / "config.json")
        except OSError:
            # 读不到真实配置也能跑，只是会退回默认配置
            pass
    return home


def start_server(config_home: Path) -> subprocess.Popen:
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["STOCK_MCPILOT_HOME"] = str(config_home)
    return subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "backend.main:app",
            "--host", HOST, "--port", str(PORT), "--log-level", "warning",
        ],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="跳过慢用例")
    args = parser.parse_args()

    config_home = make_isolated_home()
    print(f"启动后端 http://{HOST}:{PORT} （配置目录：{config_home}）")
    server = start_server(config_home)
    if not wait_for_port(HOST, PORT):
        server.kill()
        print("服务启动失败，输出：")
        print((server.stdout.read() or b"").decode("utf-8", "replace")[-4000:])
        return 1

    base = f"http://{HOST}:{PORT}"
    client = httpx.Client(base_url=base, timeout=180.0, trust_env=False)

    try:
        # ---------------- 系统 ----------------
        print("\n[系统]")
        health = client.get("/health").json()
        check("GET /health 返回 ok", health.get("status") == "ok", str(health.get("version")))
        check("服务绑定回环地址", health.get("host_binding") == "127.0.0.1", health.get("host_binding", ""))

        # ---------------- 配置与密钥安全 ----------------
        print("\n[配置与密钥安全]")
        cfg = client.get("/config").json()
        check("GET /config 返回 llm/analysis/presets",
              all(k in cfg for k in ("llm", "analysis", "presets")),
              f"{len(cfg.get('presets', {}))} 个预设")
        check("密钥以掩码形式返回（无明文）",
              "api_key_set" in cfg["llm"] and not _looks_like_secret(cfg["llm"].get("api_key", "")),
              repr(cfg["llm"].get("api_key")))
        check("存在 locked_by_env 字段", "locked_by_env" in cfg)

        legacy = client.get("/settings")
        check("GET /settings 兼容别名无重定向",
              legacy.status_code == 200 and len(legacy.history) == 0,
              f"HTTP {legacy.status_code}, history={len(legacy.history)}")

        # 写入测试：改模型名，密钥不应被掩码覆盖
        before_key_set = cfg.get("llm", {}).get("api_key_set")
        write = client.post("/config", json={"llm": {"temperature": 0.42}})
        updated = write.json() if isinstance(write.json(), dict) else {}
        # 刻意不写 updated["llm"]：写盘失败时后端返回的是 {"detail": ...}，
        # 裸 KeyError 只会说"没有 llm 键"，把真正的原因（比如沙箱拒绝写临时目录）
        # 完全藏起来。并发跑多个沙箱任务时真的会撞上这个，然后排查方向全错。
        if write.status_code != 200 or "llm" not in updated:
            detail = updated.get("detail") or write.text
            check("POST /config 可更新配置", False,
                  f"HTTP {write.status_code}：{str(detail)[:200]}")
        else:
            check("POST /config 可更新配置", abs(updated["llm"]["temperature"] - 0.42) < 1e-6,
                  f"temperature={updated['llm']['temperature']}")
            check("更新后密钥状态未受影响", updated["llm"]["api_key_set"] == before_key_set)
        client.post("/config", json={"llm": {"temperature": 0.3}})

        # ---------------- LLM ----------------
        print("\n[LLM]")
        presets = client.get("/llm/presets").json()["presets"]
        check("GET /llm/presets 覆盖主流服务商", len(presets) >= 9, f"{len(presets)} 个")
        check("预设含 ollama / lmstudio / openai / anthropic / deepseek",
              all(k in presets for k in ("ollama", "lmstudio", "openai", "anthropic", "deepseek")))

        # 远程提供商必须全部排在本地模型之前（需求里点名的一条）。
        # 这里刻意在 HTTP 层再验一次：Python dict 保序，但 JSON 序列化 / 前端渲染
        # 任何一环改了顺序，配置层自己测是测不出来的。
        groups = [item.get("group") for item in presets.values()]
        last_remote = max((i for i, g in enumerate(groups) if g == "remote"), default=-1)
        first_local = min((i for i, g in enumerate(groups) if g == "local"), default=len(groups))
        check("预设顺序：远程服务商全部在本地模型之前",
              last_remote >= 0 and first_local > last_remote,
              f"最后一个 remote 在 #{last_remote}，第一个 local 在 #{first_local}")
        check("每个预设都带 group 字段",
              all(g in ("remote", "local") for g in groups), str(groups))

        preset_groups = cfg.get("preset_groups") or []
        check("GET /config 下发分组元信息且 remote 在前",
              [g.get("key") for g in preset_groups][:2] == ["remote", "local"]
              and all(g.get("label") for g in preset_groups),
              str([g.get("key") for g in preset_groups]))

        anthropic = presets.get("anthropic") or {}
        check("Anthropic 预设使用原生协议而非 OpenAI 兼容",
              anthropic.get("kind") == "anthropic" and anthropic.get("group") == "remote",
              f"kind={anthropic.get('kind')}, group={anthropic.get('group')}")
        check("Anthropic 预设要求 API Key 且带默认模型",
              anthropic.get("requires_key") is True and bool(anthropic.get("default_model")),
              str(anthropic.get("default_model")))

        # 指向一个必然连不上的地址：要的是"返回结构化错误"，不是 500 堆栈。
        # 这条同时也覆盖了 Anthropic 分支的错误映射。
        dead = client.post("/llm/models", json={
            "preset": "anthropic", "kind": "anthropic",
            "base_url": "http://127.0.0.1:9", "api_key": "sk-ant-smoke", "model": "claude-sonnet-5",
        }).json()
        check("Anthropic 连不上时返回结构化错误而非 500",
              dead.get("ok") is False and isinstance(dead.get("kind"), str),
              f"kind={dead.get('kind')}, message={str(dead.get('message'))[:80]}")

        # 用户点的是「测试连接」这个按钮，所以 /llm/test 本身也要有一条 API 层的契约检查。
        dead_test = client.post("/llm/test", params={"deep": "true"}, json={
            "preset": "lmstudio", "kind": "openai_compat",
            "base_url": "http://127.0.0.1:9/v1", "model": "qwen/qwen3.8-27b",
        }).json()
        check("/llm/test 失败时返回结构化错误而非 500",
              dead_test.get("ok") is False and isinstance(dead_test.get("kind"), str)
              and bool(dead_test.get("message")),
              f"kind={dead_test.get('kind')}, message={str(dead_test.get('message'))[:80]}")

        models = client.post("/llm/models", json={}).json()
        check("POST /llm/models 返回模型列表", models.get("ok") and len(models.get("models", [])) > 0,
              str(models.get("models")))

        if args.quick:
            skip("POST /llm/test", "quick 模式")
            skip("POST /llm/chat 流式", "quick 模式")
        else:
            test_result = client.post("/llm/test", json={}).json()
            check("POST /llm/test 连接与推理均正常", test_result.get("ok") is True,
                  test_result.get("message", ""))

            chunks = _collect_sse(client, "/llm/chat", {"prompt": "只回复两个字：正常"})
            text = "".join(c.get("text", "") for c in chunks if c.get("type") == "delta")
            check("POST /llm/chat 流式有增量输出", len(text) > 0, f"{len(chunks)} 个事件")
            check("流式以 done 事件收尾", any(c.get("type") == "done" for c in chunks))
            check("流式未泄漏思维链", "<think" not in text.lower())

        # ---------------- 行情 ----------------
        print("\n[行情]")
        detail = client.get("/stocks/AAPL", params={"market": "US", "period": "6mo"}).json()
        check("GET /stocks/AAPL 返回报价", bool(detail.get("quote", {}).get("price")),
              f"price={detail.get('quote', {}).get('price')}")
        check("返回技术指标快照", bool(detail.get("indicators", {}).get("rsi14") is not None),
              f"RSI={detail.get('indicators', {}).get('rsi14')}")
        check("返回统计摘要", bool(detail.get("summary", {}).get("return_pct") is not None),
              f"return={detail.get('summary', {}).get('return_pct')}")
        check("返回 K 线", len(detail.get("candles", [])) > 50, f"{len(detail.get('candles', []))} 根")
        check("指标已注入 K 线", detail["candles"][-1].get("ma20") is not None)

        for market, symbol, label in (("HK", "0700", "港股"), ("CN", "600519", "A股")):
            item = client.get(f"/stocks/{symbol}", params={"market": market, "period": "1y"}).json()
            ok = bool(item.get("quote", {}).get("price")) and len(item.get("candles", [])) > 20
            check(f"{label} {symbol} 数据可用", ok,
                  f"price={item.get('quote', {}).get('price')}, {len(item.get('candles', []))} 根")

        for period, interval in (("1y", "1d"), ("2y", "1wk"), ("5y", "1mo")):
            candles = client.get("/stocks/AAPL/candles",
                                 params={"market": "US", "period": period, "interval": interval}).json()
            check(f"K线 period={period} interval={interval}",
                  candles.get("count", 0) > 5 and candles.get("interval") == interval,
                  f"{candles.get('count')} 根 / 实际 {candles.get('interval')}")

        print("\n[个股详情接口]")
        for path, key, label in (
            ("/stocks/AAPL/profile", "sector", "公司概况"),
            ("/stocks/AAPL/financials", "annual", "财务报表"),
            ("/stocks/AAPL/earnings", "eps_estimate", "财报与预测"),
            ("/stocks/AAPL/analyst", "target_mean", "分析师观点"),
        ):
            response = client.get(path)
            data = response.json() if response.status_code == 200 else {}
            check(f"{label} 可用", response.status_code == 200 and bool(data.get(key)),
                  f"HTTP {response.status_code}")

        news = client.get("/stocks/AAPL/news", params={"limit": 8}).json()
        check("新闻带原文链接", news.get("count", 0) > 0 and any(i.get("url") for i in news["items"]),
              f"{news.get('count')} 条")

        search = client.get("/stocks/search", params={"q": "apple"}).json()
        check("代码搜索可用", search.get("count", 0) > 0, f"{search.get('count')} 条")

        cn_status = client.get("/stocks/cn_names_status").json()
        check("akshare 增强状态可查询（失败也应优雅降级）",
              isinstance(cn_status.get("available"), bool), f"available={cn_status.get('available')}")

        # ---------------- AI 上下文 ----------------
        print("\n[AI 分析上下文]")
        preview = client.get("/analysis/context", params={"symbol": "AAPL", "market": "US"}).json()
        meta = preview.get("meta", {})
        text = preview.get("text", "")
        expected_sections = {"quote", "indicators", "summary", "candles", "profile",
                             "financials", "earnings", "analyst", "news"}
        included = set(meta.get("included", []))
        check("上下文包含全部 9 个数据段", expected_sections <= included,
              f"缺 {sorted(expected_sections - included)}" if expected_sections - included else "9/9")
        check("上下文文本非空", len(text) > 2000, f"{len(text)} 字符")
        check("上下文含行情/指标/财报/新闻字样",
              all(k in text for k in ("最新行情", "技术指标", "财务报表", "近期新闻")))
        check("用户提示词含输出要求", "输出要求" in preview.get("structured", {}).get("user_prompt", ""))
        check("系统提示词声明不编造数据",
              "绝不编造" in preview.get("structured", {}).get("system_prompt", ""))
        check("上下文在预算内", meta.get("context_chars", 0) <= meta.get("budget_chars", 1),
              f"{meta.get('context_chars')} / {meta.get('budget_chars')}")

        # ---------------- 榜单 ----------------
        print("\n[榜单]")
        movers = client.get("/stocks/movers", params={"market": "US", "type": "gainers", "count": 10}).json()
        check("美股涨幅榜可用", movers.get("count", 0) > 0, f"{movers.get('count')} 条")
        if movers.get("items"):
            check("涨幅榜全为正涨幅", all((i.get("change_pct") or 0) > 0 for i in movers["items"]))
            check("涨幅榜按降序排列",
                  all((movers["items"][i]["change_pct"] or 0) >= (movers["items"][i + 1]["change_pct"] or 0)
                      for i in range(len(movers["items"]) - 1)))
        losers = client.get("/stocks/movers", params={"market": "US", "type": "losers", "count": 10}).json()
        check("美股跌幅榜全为负涨幅",
              bool(losers.get("items")) and all((i.get("change_pct") or 0) < 0 for i in losers["items"]),
              f"{losers.get('count')} 条")

        if args.quick:
            skip("港股/A股 涨跌榜", "quick 模式")
            skip("财报日历", "quick 模式")
        else:
            for market, label in (("HK", "港股"), ("CN", "A股")):
                board = client.get("/stocks/movers", params={"market": market, "type": "gainers", "count": 8}).json()
                check(f"{label}涨幅榜可用", board.get("count", 0) > 0, f"{board.get('count')} 条")

            upcoming = client.get("/stocks/upcoming_earnings",
                                  params={"market": "US", "days": 30, "limit": 20}).json()
            check("财报日历可用", upcoming.get("count", 0) > 0, f"{upcoming.get('count')} 条")
            if upcoming.get("items"):
                check("财报日历按日期升序",
                      all(upcoming["items"][i]["earnings_date"] <= upcoming["items"][i + 1]["earnings_date"]
                          for i in range(len(upcoming["items"]) - 1)))

        # ---------------- 非流式分析 ----------------
        if args.quick:
            skip("POST /analysis 完整分析", "quick 模式")
        else:
            print("\n[AI 分析]")
            analysis = client.post("/analysis", json={
                "symbol": "AAPL", "market": "US", "days": 120,
                "question": "当前技术面与基本面是否一致？",
            }).json()
            body = analysis.get("analysis", "")
            check("POST /analysis 返回分析文本", len(body) > 100, f"{len(body)} 字符")
            check("分析结果带上下文元信息", bool(analysis.get("context_meta")))
            check("分析标注了所用模型", bool(analysis.get("model")), str(analysis.get("model")))
            check("分析耗时已记录", isinstance(analysis.get("elapsed_ms"), int),
                  f"{analysis.get('elapsed_ms')} ms")

            streamed = _collect_sse(client, "/analysis/stream",
                                    {"symbol": "AAPL", "market": "US", "days": 60})
            stream_text = "".join(c.get("text", "") for c in streamed if c.get("type") == "delta")
            check("POST /analysis/stream 流式输出", len(stream_text) > 100, f"{len(stream_text)} 字符")
            check("流式 meta 事件带上下文元信息",
                  any(c.get("type") == "meta" and c.get("context_meta") for c in streamed))

        # ---------------- 错误处理 ----------------
        print("\n[错误处理]")
        bad = client.get("/stocks/ZZZZZZ", params={"market": "US"})
        check("格式合法但不存在的代码不返回 500",
              bad.status_code in (200, 404), f"HTTP {bad.status_code}")
        bad_market = client.get("/stocks/AAPL", params={"market": "XX"})
        check("非法市场参数被拒", bad_market.status_code == 422, f"HTTP {bad_market.status_code}")
        bad_symbol = client.get("/stocks/" + "X" * 40, params={"market": "US"})
        check("超长代码被参数校验拦下", bad_symbol.status_code == 422, f"HTTP {bad_symbol.status_code}")
        bad_period = client.get("/stocks/AAPL/candles", params={"market": "US", "period": "bogus"})
        check("非法周期参数被拒", bad_period.status_code == 422, f"HTTP {bad_period.status_code}")

    finally:
        client.close()
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
        shutil.rmtree(config_home, ignore_errors=True)

    # ---------------- 汇总 ----------------
    print("\n" + "=" * 62)
    print(f"通过 {len(PASSED)}  失败 {len(FAILED)}  跳过 {len(SKIPPED)}")
    if FAILED:
        print("\n失败项：")
        for name, detail in FAILED:
            print(f"  - {name}  {detail}")
    print("=" * 62)
    return 1 if FAILED else 0


def _collect_sse(client: httpx.Client, path: str, payload: dict) -> list[dict]:
    """消费 SSE 端点，返回事件列表。"""
    import json

    events: list[dict] = []
    with client.stream("POST", path, json=payload) as response:
        if response.status_code != 200:
            return events
        for line in response.iter_lines():
            if not line:
                continue
            if line.startswith("data:"):
                line = line[5:].strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def _looks_like_secret(value: str) -> bool:
    """掩码里不该出现完整密钥特征（长且无星号）。"""
    if not value:
        return False
    return "*" not in value and len(value) > 12


if __name__ == "__main__":
    raise SystemExit(main())
