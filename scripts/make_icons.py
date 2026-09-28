#!/usr/bin/env python3
"""生成 Tauri 应用图标（src-tauri/icons/）。

设计取向
--------
先调研了 App Store 上同类应用的图标，已被占用的母题有：
红底白 K 线（同花顺/东方财富）、黑底青折线（股市/TradingView）、蓝底白折线或
字标（蚂蚁财富/新浪财经/CNBC）、汉字「涨」「开盘」、动物吉祥物、单色向上箭头。

**没人用"AI 读数"这个角度**，而这正是本应用的核心差异。所以：

  - 深墨蓝底 —— 同类里没有（不是红、不是亮蓝、不是黑）
  - 一绿一红两根蜡烛，直接复用应用内的涨跌配色常量（红涨绿跌）
  - 一条带数据点的水平分析线压在上方 —— 读作"被测量、被分析"

形状
----
macOS 图标是**超椭圆**而不是圆角矩形，圆角矩形摆在系统图标旁边会明显偏方。
指数 n = 4.8（实测值，常见引用 5.0 偏方），内容占 1024 画布的 824（Apple 的留白
惯例）。用 4 倍超采样 + LANCZOS 缩放做抗锯齿。

刻意不用 headless Chrome 光栅化 SVG：这套图形全是直线与多边形，Pillow 超采样
的结果没有可见差别，而少一个浏览器依赖意味着这个脚本能在任何有 Pillow 的
环境里重跑。

尺寸分层
--------
`.icns` 的每个槽位可以放**不同的图**。512 上好看的设计直接缩到 16 会糊成一团，
所以按尺寸换图而不是缩放。分界线不是拍脑袋定的，而是按"每个元素在目标尺寸下
至少要有 2 像素"反推出来的 —— 低于 2px 的元素不是"变小"，是变成灰雾：

    元素        设计宽度   在 128px 下   在 64px 下   在 32px 下
    蜡烛实体      132        16.5px        8.3px        4.1px
    影线           20         2.5px        1.25px  ✗
    分析线         16         2.0px        1.0px   ✗

所以 32px 只能保留实体，64px 起才谈得上影线，而影线与分析线在小尺寸下必须
**加粗**（不是缩小）才能站住。每层的几何参数见 LAYOUTS，一眼能改。

用法
----
    python scripts/make_icons.py            # 生成到 src-tauri/icons/
"""

from __future__ import annotations

import math
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

# --------------------------------------------------------------------------
# 参数
# --------------------------------------------------------------------------

CANVAS = 1024
CONTENT = 824  # 内容边长：824/1024 是 Apple 图标的留白惯例
EXPONENT = 4.8  # 超椭圆指数，实测自系统图标
SUPERSAMPLE = 4  # 超采样倍数（大尺寸降到 2，省内存且看不出差别）

BG_TOP = (32, 44, 68)  # #202c44
BG_BOTTOM = (15, 23, 40)  # #0f1728
UP = (217, 63, 76)  # #d93f4c —— 与应用内涨色一致
DOWN = (31, 157, 99)  # #1f9d63 —— 与应用内跌色一致
INK = (236, 242, 252)  # 分析线用的近白

# 设计坐标下的原始几何（tier 3 用）。
BASE_Y = 690
BODY_W = 132
LEFT_CX, LEFT_TOP = 400, 512  # 绿的：跌，短
RIGHT_CX, RIGHT_TOP = 624, 320  # 红的：涨，长
WICK_W = 20
WICK_PAD = 62
LINE_Y = 246
LINE_X0, LINE_X1 = 262, 792
LINE_W = 16
DOT_R = 30

# 构图整体缩放（围绕画布中心）。蜡烛按原始尺寸画出来偏小、四周留白偏多，
# 放大一档后填充感明显更好。上界由 verify_within_content() 守着 —— 放大过头
# 会让影线或分析线戳出超椭圆。
ZOOM = 1.18


@dataclass(frozen=True)
class Layout:
    """某一层的几何。小尺寸不是把大图缩小，而是换一套参数。"""

    body_w: float
    left_cx: float
    right_cx: float
    left_top: float
    right_top: float
    base_y: float
    line_y: float
    wick_w: float
    wick_pad: float
    line_w: float
    dot_r: float
    show_wicks: bool
    show_line: bool
    show_dot: bool


LAYOUTS = {
    # 0: <=32px —— 只留背景 + 两块实体。4px 宽的蜡烛上再画 1px 的线只会变灰。
    0: Layout(250, 320, 704, 470, 300, 720, 230, 0, 0, 0, 0, False, False, False),
    # 1: 33-63px —— 加回分析线，宽度 64 设计像素（32px 下正好 2px）
    1: Layout(180, 360, 664, 490, 310, 706, 230, 0, 0, 64, 0, False, True, False),
    # 2: 64-127px —— 加回影线（32 设计像素 → 64px 下 2px）
    2: Layout(150, 384, 640, 500, 314, 698, 240, 32, 56, 32, 0, True, True, False),
    # 3: >=128px —— 完整设计，此时影线 2.5px、分析线 2px、数据点 7.5px
    3: Layout(
        BODY_W, LEFT_CX, RIGHT_CX, LEFT_TOP, RIGHT_TOP, BASE_Y, LINE_Y,
        WICK_W, WICK_PAD, LINE_W, DOT_R, True, True, True,
    ),
}

# 每个 .icns 槽位用哪一层的尺寸
ICNS_SLOTS = {
    "icon_16x16.png": 16,
    "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32,
    "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128,
    "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256,
    "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512,
    "icon_512x512@2x.png": 1024,
}


def tier_for(size: int) -> int:
    if size <= 32:
        return 0
    if size <= 63:
        return 1
    if size <= 127:
        return 2
    return 3


# --------------------------------------------------------------------------
# 绘制
# --------------------------------------------------------------------------


def superellipse_points(canvas: int, content: float, exponent: float, steps: int = 720):
    """超椭圆 |x/a|^n + |y/a|^n = 1 的参数化采样。"""
    a = content / 2
    cx = cy = canvas / 2
    power = 2.0 / exponent
    points = []
    for i in range(steps):
        t = 2 * math.pi * i / steps
        ct, st = math.cos(t), math.sin(t)
        x = a * math.copysign(abs(ct) ** power, ct)
        y = a * math.copysign(abs(st) ** power, st)
        points.append((cx + x, cy + y))
    return points


def gradient(size: int, top: tuple, bottom: tuple) -> Image.Image:
    img = Image.new("RGB", (size, size))
    draw = ImageDraw.Draw(img)
    for y in range(size):
        k = y / max(size - 1, 1)
        draw.line(
            [(0, y), (size, y)],
            fill=tuple(round(top[i] + (bottom[i] - top[i]) * k) for i in range(3)),
        )
    return img


def render(size: int) -> Image.Image:
    """渲染一个尺寸的图标。"""
    scale = SUPERSAMPLE if size <= 256 else 2
    s = size * scale
    k = s / CANVAS  # 设计坐标 -> 本次渲染坐标
    lay = LAYOUTS[tier_for(size)]

    # 构图缩放：围绕画布中心等比放大，宽度与位置一起放大
    def z(v: float) -> float:
        return (v - CANVAS / 2) * ZOOM + CANVAS / 2

    # 背景：超椭圆裁切的竖向渐变
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).polygon(superellipse_points(s, CONTENT * k, EXPONENT), fill=255)
    canvas = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    canvas.paste(gradient(s, BG_TOP, BG_BOTTOM).convert("RGBA"), (0, 0), mask)

    draw = ImageDraw.Draw(canvas)

    def rect(x0: float, y0: float, x1: float, y1: float, color) -> None:
        draw.rectangle([z(x0) * k, z(y0) * k, z(x1) * k, z(y1) * k], fill=color)

    if lay.show_wicks:
        for cx, top in ((lay.left_cx, lay.left_top), (lay.right_cx, lay.right_top)):
            rect(
                cx - lay.wick_w / 2,
                top - lay.wick_pad,
                cx + lay.wick_w / 2,
                lay.base_y + lay.wick_pad,
                INK,
            )

    # 蜡烛实体：绿（跌）在左，红（涨）在右
    rect(
        lay.left_cx - lay.body_w / 2, lay.left_top,
        lay.left_cx + lay.body_w / 2, lay.base_y, DOWN,
    )
    rect(
        lay.right_cx - lay.body_w / 2, lay.right_top,
        lay.right_cx + lay.body_w / 2, lay.base_y, UP,
    )

    if lay.show_line:
        half = lay.line_w / 2
        rect(LINE_X0, lay.line_y - half, LINE_X1, lay.line_y + half, INK)
        if lay.show_dot:
            draw.ellipse(
                [
                    z(LINE_X1 - lay.dot_r) * k, z(lay.line_y - lay.dot_r) * k,
                    z(LINE_X1 + lay.dot_r) * k, z(lay.line_y + lay.dot_r) * k,
                ],
                fill=INK,
            )

    return canvas.resize((size, size), Image.LANCZOS)


def verify_within_content() -> None:
    """所有绘制坐标必须落在超椭圆的内容方框内。

    ZOOM 放大过头时最先出事的是影线末端和分析线两端 —— 它们会戳出圆角，
    在透明区留下一截突兀的色块。与其肉眼在 1024 上找，不如直接算。
    """
    lo, hi = (CANVAS - CONTENT) / 2, (CANVAS + CONTENT) / 2
    problems = []
    for tier, lay in LAYOUTS.items():
        pts = [
            (lay.left_cx - lay.body_w / 2, lay.left_top),
            (lay.right_cx + lay.body_w / 2, lay.base_y),
        ]
        if lay.show_wicks:
            pts += [
                (lay.left_cx, lay.left_top - lay.wick_pad),
                (lay.right_cx, lay.base_y + lay.wick_pad),
            ]
        if lay.show_line:
            pts += [(LINE_X0, lay.line_y), (LINE_X1, lay.line_y)]
            if lay.show_dot:
                pts += [(LINE_X1 + lay.dot_r, lay.line_y + lay.dot_r)]
        for x, y in pts:
            zx = (x - CANVAS / 2) * ZOOM + CANVAS / 2
            zy = (y - CANVAS / 2) * ZOOM + CANVAS / 2
            if not (lo <= zx <= hi and lo <= zy <= hi):
                problems.append(f"tier{tier}: ({x:.0f},{y:.0f}) -> ({zx:.0f},{zy:.0f})")
    assert not problems, "构图溢出内容区：" + "; ".join(problems)


# --------------------------------------------------------------------------
# 校验
# --------------------------------------------------------------------------


def verify_alpha(img: Image.Image, size: int, label: str) -> None:
    """确认透明角与不透明中心 —— 少了 alpha 就是一个白方块。"""
    alpha = img.convert("RGBA").getchannel("A")
    lo, hi = alpha.getextrema()
    assert (lo, hi) == (0, 255), f"{label}: alpha 范围异常 {(lo, hi)}"
    assert alpha.getpixel((size // 2, size // 2)) == 255, f"{label}: 中心不透明"
    assert alpha.getpixel((0, 0)) == 0, f"{label}: 角上不透明"


def classify(px, palette, tol=48):
    """把像素归到最接近的调色板项；超出容差返回 None。

    不能用精确相等：LANCZOS 降采样之后每个像素都被邻域影响，纯色像素可能
    一个都不剩（这正是第一版断言全部数出 0 的原因）。
    """
    best, best_d = None, tol
    for name, color in palette.items():
        d = sum((px[i] - color[i]) ** 2 for i in range(3)) ** 0.5
        if d < best_d:
            best, best_d = name, d
    return best


def count_elements(img: Image.Image) -> dict[str, int]:
    size = img.width
    px = img.load()
    palette = {"bg": BG_BOTTOM, "up": UP, "down": DOWN, "ink": INK}
    counts = {name: 0 for name in palette}
    for y in range(size):
        for x in range(size):
            r, g, b, a = px[x, y]
            if a < 200:
                continue
            name = classify((r, g, b), palette)
            if name:
                counts[name] += 1
    return counts


def build_icns(iconset_dir: Path, out: Path) -> None:
    result = subprocess.run(
        ["iconutil", "-c", "icns", str(iconset_dir), "-o", str(out)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"iconutil 失败：{result.stderr.strip()}")


def verify_icns(path: Path) -> list[str]:
    """解析 icns 容器：校验总长自洽，并列出实际的类型码。"""
    data = path.read_bytes()
    if data[:4] != b"icns":
        raise SystemExit("不是 icns 文件")
    declared = int.from_bytes(data[4:8], "big")
    if declared != len(data):
        raise SystemExit(f"icns 声明长度 {declared} != 实际 {len(data)}")

    types, offset = [], 8
    while offset + 8 <= len(data):
        code = data[offset : offset + 4].decode("ascii", "replace")
        length = int.from_bytes(data[offset + 4 : offset + 8], "big")
        if length <= 0:
            break
        types.append(code)
        offset += length
    return types


# --------------------------------------------------------------------------


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    icons = root / "src-tauri" / "icons"
    icons.mkdir(parents=True, exist_ok=True)

    verify_within_content()

    print("各尺寸下的元素像素分布（验证小尺寸没有糊掉）")
    for size in (16, 32, 64, 128, 256):
        img = render(size)
        verify_alpha(img, size, f"{size}px")
        counts = count_elements(img)
        total = size * size
        parts = "  ".join(
            f"{name}={counts[name]:>5}({counts[name] * 100 / total:4.1f}%)"
            for name in ("bg", "up", "down", "ink")
        )
        print(f"  {size:>4}px tier={tier_for(size)}  {parts}")
        if size <= 32:
            assert counts["up"] > 0 and counts["down"] > 0, (
                f"{size}px: 涨跌两色必须都还看得见"
            )

    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "AppIcon.iconset"
        iconset.mkdir()
        for slot, size in ICNS_SLOTS.items():
            render(size).save(iconset / slot)
        build_icns(iconset, icons / "icon.icns")

    # Tauri 默认图标清单要求这五个文件；icon.png 是 generate_context! 编译期
    # 要读的窗口图标，缺了直接编译不过。
    render(32).save(icons / "32x32.png")
    render(128).save(icons / "128x128.png")
    render(256).save(icons / "128x128@2x.png")
    render(1024).save(icons / "icon.png")

    # .ico 各尺寸独立绘制，让 Windows 也吃到尺寸分层
    ico_sizes = [16, 32, 48, 64, 128, 256]
    render(256).save(
        icons / "icon.ico",
        sizes=[(s, s) for s in ico_sizes],
        append_images=[render(s) for s in ico_sizes if s != 256],
    )

    types = verify_icns(icons / "icon.icns")
    expected = {
        "ic04", "ic05", "ic07", "ic08", "ic09",
        "ic10", "ic11", "ic12", "ic13", "ic14",
    }
    missing = expected - set(types)
    print(f"\nicon.icns 槽位：{' '.join(sorted(types))}")
    assert not missing, f"icns 缺少槽位：{sorted(missing)}"
    print("icns 10 个尺寸槽位齐全")

    print(f"\n输出目录：{icons}")
    for path in sorted(icons.iterdir()):
        print(f"  {path.name:22s} {path.stat().st_size:>9,} B")
    return 0


if __name__ == "__main__":
    sys.exit(main())
