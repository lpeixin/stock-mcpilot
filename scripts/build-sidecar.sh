#!/usr/bin/env bash
#
# 把 Python 后端打包成 Tauri 的 sidecar 可执行文件。
#
# 产出：src-tauri/binaries/stock-mcpilot-server-<target-triple>
# 之后用带上 bundle 覆盖配置的方式打包整个应用：
#
#   scripts/build-sidecar.sh
#   cd frontend && npm run tauri build -- --config ../src-tauri/tauri.bundle.conf.json
#
# 为什么 externalBin 不写在主配置里：tauri-build 在 `cargo check` 与 `tauri dev`
# 阶段就会校验它，sidecar 不存在时直接编译失败 —— 那会把开发模式一起拖垮。
# 所以放在 tauri.bundle.conf.json 里，只在真正打包时叠加。
#
# 关于启动速度：这里用 --onefile（Tauri 的 externalBin 只接受单个文件）。
# onefile 每次启动都要把内容解压到临时目录，冷启动 5-15 秒是正常的 —— 所以
# src-tauri/src/backend.rs 里 READY_TIMEOUT 给到 90 秒，而不是常见的 10 秒。
# 另外 onefile 的引导器会 fork 出真正的 Python 进程，只 kill 父进程会留下占着
# 端口的孤儿，这也是那边 spawn 时用 process_group(0) 的原因。

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${SMP_PYTHON:-$ROOT/.venv/bin/python}"
ENTRY="$ROOT/run.py"
NAME="stock-mcpilot-server"

if [[ ! -x "$PYTHON" ]]; then
  echo "找不到 Python 解释器：$PYTHON" >&2
  echo "先建虚拟环境并装依赖：" >&2
  echo "  python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt" >&2
  exit 1
fi

TRIPLE="$(rustc --print host-tuple 2>/dev/null || rustc -Vv | awk '/^host:/{print $2}')"
if [[ -z "$TRIPLE" ]]; then
  echo "无法确定 target triple，请确认 rustc 可用" >&2
  exit 1
fi

echo "解释器    : $PYTHON"
echo "目标平台  : $TRIPLE"
echo "入口      : $ENTRY"

if ! "$PYTHON" -c "import PyInstaller" 2>/dev/null; then
  echo "安装 PyInstaller ..."
  "$PYTHON" -m pip install --quiet --upgrade pyinstaller
fi

# PyInstaller 的中间产物有几十个文件。刻意不放在仓库里、也不在结尾 `rm -rf`
# 清理：受限沙箱（以及很多企业环境）会拦截批量删除，脚本会因为"清理"这种无关
# 紧要的一步而整体失败。用一次性临时目录，交给系统回收，仓库里不留东西。
WORK="$(mktemp -d "${TMPDIR:-/tmp}/smp-sidecar.XXXXXX")"
mkdir -p "$ROOT/src-tauri/binaries"

# uvicorn 大量使用字符串动态导入，PyInstaller 的静态分析抓不到，
# 必须显式列出来，否则打包后启动会报 "Could not import module ..."。
HIDDEN=(
  uvicorn.logging
  uvicorn.loops.auto
  uvicorn.loops.asyncio
  uvicorn.protocols.http.auto
  uvicorn.protocols.http.h11_impl
  uvicorn.protocols.websockets.auto
  uvicorn.lifespan.on
  uvicorn.lifespan.off
)
HIDDEN_ARGS=()
for mod in "${HIDDEN[@]}"; do
  HIDDEN_ARGS+=(--hidden-import "$mod")
done

echo "开始打包（首次通常要几分钟）..."
# 刻意不加 --clean：它会去删 PyInstaller 自己的全局缓存目录（几十个文件），
# 在受限沙箱/企业环境里会被批量删除守卫拦下，脚本因此整个失败。而 --clean 只是
# "别用缓存、从头来"的便利选项 —— 复用缓存反而让重复构建更快。
"$PYTHON" -m PyInstaller \
  --noconfirm \
  --onefile \
  --console \
  --name "$NAME" \
  --distpath "$WORK/dist" \
  --workpath "$WORK/work" \
  --specpath "$WORK" \
  --paths "$ROOT" \
  "${HIDDEN_ARGS[@]}" \
  --collect-submodules backend \
  --collect-submodules uvicorn \
  --collect-submodules yfinance \
  --collect-submodules akshare \
  --collect-data certifi \
  --exclude-module matplotlib \
  --exclude-module tkinter \
  --exclude-module PyQt5 \
  --exclude-module PySide6 \
  --exclude-module IPython \
  --exclude-module notebook \
  --exclude-module pytest \
  "$ENTRY"

BUILT="$WORK/dist/$NAME"
[[ -f "$BUILT" ]] || { echo "打包失败：没有产出 $BUILT" >&2; exit 1; }

TARGET="$ROOT/src-tauri/binaries/$NAME-$TRIPLE"
cp "$BUILT" "$TARGET"
chmod +x "$TARGET"

echo
echo "完成：$TARGET"
echo "大小：$(du -h "$TARGET" | cut -f1)"
# 注意 ${WORK} 的大括号：bash 把紧随其后的全角括号当成变量名的一部分，
# 写成 `$WORK（...` 会被解析成变量 `WORK（...` 然后报 unbound variable。
# 这个脚本里变量后面只要跟中文，一律加花括号。
echo "中间产物：${WORK}（可自行删除）"

# 冒烟：起一次、探测 /health、收尾。打包产物的失败模式（隐藏导入漏了、数据文件
# 没带上）只有在真正运行时才暴露，而那时候已经是用户面前了。
#
# 整段放在**一个 Python 进程**里做，而不是 bash 的 `cmd &` + `kill`：
#   1. bash 的后台作业不带自己的进程组，`kill -TERM -$PID` 打的是一个不存在的
#      组（被 `|| true` 吞掉），sidecar 永远不死，随后的 `wait` 永久阻塞 ——
#      这个脚本第一版就这么卡住过一次。
#   2. onefile 的引导器会 fork 出真正的 Python 进程，只杀父进程会留下占着端口的
#      孤儿。Python 里用 process_group=0 起进程，就能整组收掉。
#   3. 每轮探测都新起一个解释器太慢（90 轮能跑五分钟）。
echo
echo "冒烟测试打包产物 ..."
PORT="${SMP_SIDECAR_PORT:-8177}"
if ! "$PYTHON" - "$TARGET" "$PORT" "$WORK/smoke.log" <<'PY'
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

binary, port, log_path = sys.argv[1], sys.argv[2], sys.argv[3]
# 绕开代理：很多环境设了 HTTP_PROXY，那会把 127.0.0.1 也一起代理走。
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

log = open(log_path, "w")
proc = subprocess.Popen(
    [binary, "--host", "127.0.0.1", "--port", port],
    stdout=log, stderr=subprocess.STDOUT,
    process_group=0,  # 自成进程组，收尾时能整组带走
)

started = time.time()
healthy = False
try:
    deadline = started + 90
    while time.time() < deadline:
        if proc.poll() is not None:
            print(f"sidecar 启动即退出（码 {proc.returncode}）", file=sys.stderr)
            break
        try:
            body = json.load(opener.open(f"http://127.0.0.1:{port}/health", timeout=3))
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            time.sleep(1)
            continue
        healthy = body.get("status") == "ok"
        break
finally:
    # 先礼后兵，并且一定要 wait —— 否则留下僵尸，也漏掉端口没释放的情况
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except OSError:
        pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        proc.wait()
    log.close()

if healthy:
    print(f"冒烟测试通过：/health 返回 status=ok（冷启动 {time.time() - started:.1f}s）")
    sys.exit(0)
print("冒烟测试失败：sidecar 没能在 90 秒内响应 /health", file=sys.stderr)
sys.exit(1)
PY
then
  echo "--- sidecar 输出尾部 ---" >&2
  tail -30 "$WORK/smoke.log" >&2
  exit 1
fi
