"""端到端真实运行 + 截图，给论文 §4.5.3 做插图素材。

流程：
  1. 启动 Chromium → 打开 ChemMaster Web
  2. 截图 1：首页（空状态 + 3 个示例 prompt + 右侧 Engines/Skills/Benchmark）
  3. 点击"算一下水分子的能量"示例
  4. 等 confirm 卡片出现 → 截图 2：confirm 卡片（参数表格 + 右侧时间线）
  5. 点"同意执行"
  6. 等若干步后 → 截图 3：步骤时间线滚动中（含 L1 自主恢复）
  7. 等任务完成 → 截图 4：最终结果（markdown 摘要 + key_results 表格）

输出至 benchmarks/use_cases/end_to_end_demo/screenshots/
"""
from __future__ import annotations

import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

WEB_URL = "http://127.0.0.1:8765/"
OUT_DIR = Path(__file__).resolve().parents[2] / "benchmarks" / "use_cases" / "end_to_end_demo" / "screenshots"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def auto_respond(deadline: float) -> str | None:
    """轮询所有任务，自动同意 confirm/recommend 卡片，返回 task_id。"""
    seen_task: str | None = None
    while time.time() < deadline:
        # 不通过 web，直接查 API（playwright 也在跑别的截图）
        try:
            # 发现当前 task：从 Web 前端的 /api/run 之后的某个 task
            # 简化：返回 None 让外层处理
            pass
        except Exception:
            pass
        time.sleep(0.5)
    return None


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 900},
            device_scale_factor=2,  # retina 清晰度
            locale="zh-CN",
        )
        page = ctx.new_page()
        page.goto(WEB_URL)
        page.wait_for_selector("#chat", timeout=10_000)
        time.sleep(1.5)  # 等右侧异步面板加载完

        # —— 截图 1：首页（空状态 + 示例 prompt）——
        s1 = OUT_DIR / "01_homepage_empty.png"
        page.screenshot(path=str(s1), full_page=False)
        print(f"[1/4] 首页 → {s1.name}")

        # —— 提交任务 ——
        page.click('button.ex:has-text("算一下水分子的能量")')

        # —— 等 confirm 卡片 ——
        try:
            page.wait_for_selector(".conf, .rec", timeout=60_000)
        except Exception as e:
            print(f"等待 confirm/recommend 超时：{e}")

        time.sleep(1)
        # —— 截图 2：confirm/recommend 卡片 + 右侧时间线 ——
        s2 = OUT_DIR / "02_confirm_card.png"
        page.screenshot(path=str(s2), full_page=False)
        print(f"[2/4] confirm 卡片 → {s2.name}")

        # —— 自动同意所有 confirm/recommend 卡片 ——
        deadline = time.time() + 240
        last_n = 0
        captured_step_screenshot = False
        while time.time() < deadline:
            # 优先点 recommend 的"接受"
            for sel in [
                ".rec button.btn:has-text('接受')",
                ".conf button.btn:has-text('同意执行')",
            ]:
                btns = page.locator(sel).all()
                for b in btns:
                    try:
                        b.click(timeout=1500)
                        time.sleep(0.5)
                    except Exception:
                        pass

            # 拉当前 currentTask 信息
            try:
                ev_count = page.evaluate("document.querySelectorAll('#timeline .step-row').length")
            except Exception:
                ev_count = 0

            # 当时间线达到 ≥3 步时拍第三张（多看几次成功+失败行）
            if not captured_step_screenshot and ev_count >= 5:
                s3 = OUT_DIR / "03_timeline_running.png"
                page.screenshot(path=str(s3), full_page=False)
                print(f"[3/4] 时间线滚动中（{ev_count} 步）→ {s3.name}")
                captured_step_screenshot = True

            # 检查任务结束（active 区显示空闲中）
            try:
                active_text = page.locator("#active").inner_text()
            except Exception:
                active_text = ""
            if "空闲" in active_text and ev_count > 0:
                # 任务跑完
                break

            time.sleep(1.0)

        # 滚到 chat 底部，让最终结果可见
        page.evaluate("document.getElementById('chat').scrollTop = 99999")
        time.sleep(1)

        # —— 截图 4：最终结果（markdown 摘要 + key_results 表）——
        s4 = OUT_DIR / "04_final_result.png"
        page.screenshot(path=str(s4), full_page=False)
        print(f"[4/4] 最终结果 → {s4.name}")

        # 多拍一张全页面长图作为附录材料
        s5 = OUT_DIR / "05_full_page.png"
        page.screenshot(path=str(s5), full_page=True)
        print(f"[+]  全页面长图 → {s5.name}")

        ctx.close()
        browser.close()

    print(f"\n所有截图存于：{OUT_DIR}")
    for f in sorted(OUT_DIR.glob("*.png")):
        size_kb = f.stat().st_size / 1024
        print(f"  - {f.name}  ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
