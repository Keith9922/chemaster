#!/usr/bin/env python3
"""自动裁剪 Mac 终端截图——去掉底部空白，保留终端窗口本身.

逻辑：
- Mac 终端窗口的标题栏是浅灰色，主体是黑色（或近黑）
- 命令行结尾后大片是黑色，但用户截到了整个屏幕区域
- 找到内容行（含非空命令文本）的最末一行，从那里向下保留 ~20% 高度作为下边距，
  其余切掉
- 同时去掉两侧无关空白（基本不动，只裁底部）
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "paper" / "figures" / "v3_real"


def crop_terminal(in_path: Path, out_path: Path,
                  bottom_padding_px: int = 25) -> None:
    """智能裁剪：只看终端窗口中央 60% 的水平带。

    终端窗口边框（左右滚动条、阴影边）给所有行都贡献方差，会误判"空行"也有内容。
    解决方法：只统计图像水平 20%–80% 区间内每行的方差。
    """
    img = Image.open(in_path).convert("RGB")
    arr = np.array(img)
    h, w = arr.shape[:2]

    # 用更窄的中央带（30%–70%），且只把"明显的字符"视为内容
    x_lo = int(w * 0.30)
    x_hi = int(w * 0.70)
    central = arr[:, x_lo:x_hi, :].mean(axis=2)  # (h, central_w)

    # 终端文字通常灰度 > 150（白）或 > 100（彩色）；
    # 边框、轻微阴影通常 < 80。设阈值为 100。
    bright_mask = central > 100
    n_bright_per_row = bright_mask.sum(axis=1)

    # 终端一行可见文字至少 30+ 像素是亮的（一个 ASCII 字符约 6×12 像素）
    has_content = n_bright_per_row > 30

    content_rows = np.where(has_content)[0]
    if len(content_rows) == 0:
        img.save(out_path)
        return

    # 从底向上找：跳过零星的边框噪声（连续 < 3 个有内容的行视为噪声）
    # 实际上更稳的做法：找到从底往上数第一个"含真实文字"的行
    last_content = int(content_rows[-1])

    # 但若最后内容行的下一行立即是黑、且持续大段黑，那才是真的底部
    # 检查 last_content 下方 50px 内是否还有亮行；如果有，向后延伸
    crop_bottom = min(last_content + bottom_padding_px, h)
    cropped = img.crop((0, 0, w, crop_bottom))
    cropped.save(out_path, optimize=True)
    print(f"  → {out_path.name}  原 {h}px → 裁后 {crop_bottom}px"
          f"  (去除 {h - crop_bottom}px 底部空白)")


def main():
    # 经实际内容核对后的真实映射（用户截图的命令执行顺序与文件时间戳）：
    pairs = [
        ("raw_s22.png",         "fig_real_pytest.png"),       # 实际是 pytest
        ("raw_mcp.png",         "fig_real_engineering.png"),  # 实际是 engineering
        ("raw_engineering.png", "fig_real_mcp_probe.png"),    # 实际是 mcp
        ("raw_pytest.png",      "fig_real_s22.png"),          # 实际是 s22
    ]
    for raw, out in pairs:
        in_path = SRC / raw
        out_path = SRC / out
        if in_path.exists():
            crop_terminal(in_path, out_path, bottom_padding_px=40)
        else:
            print(f"  ✗ {in_path} 不存在")


if __name__ == "__main__":
    main()
