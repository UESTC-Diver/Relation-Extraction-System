# -*- coding: utf-8 -*-
"""v2.6.0 真出图：新文案首页 + 抽取过程演绎（桌面/390）。

截图路径相对项目根（Path(__file__).parents[2]），避免再产生 backend/docs 误目录。
"""
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)
EXE = os.path.join(
    os.environ["LOCALAPPDATA"], "ms-playwright", "chromium-1248", "chrome-win64", "chrome.exe"
)
BASE = "http://127.0.0.1:8000"


def shot(pg, name):
    path = OUT / name
    pg.screenshot(path=str(path))
    overflow = pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    print(f"{name}: saved, horizontal overflow = {overflow}px")


def open_app_from_landing(pg):
    """从首页点「进入工作台」——这条路径同时验证 SPA 转场与可重入初始化。"""
    pg.goto(BASE, wait_until="networkidle")
    pg.get_by_role("link", name="进入工作台").first.click()
    pg.wait_for_url("**/app")
    pg.wait_for_timeout(1500)
    return pg.evaluate("location.pathname")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=EXE)

        # 1) 桌面首页：新文案口径
        pg = browser.new_page(viewport={"width": 1440, "height": 900})
        pg.goto(BASE, wait_until="networkidle")
        pg.wait_for_timeout(600)
        shot(pg, "42-landing-new-copy.png")
        assert "中英文本里" in pg.locator("#lp-headline").inner_text()
        assert "spaCy" in pg.locator(".lp-sub").first.inner_text()

        # 2) SPA 导航进工作台：确认数据非空（转场 + 初始化回归）
        path = open_app_from_landing(pg)
        assert path == "/app", path
        counts = pg.locator(".cp-meta dd").all_inner_texts()
        print("workbench counts after SPA nav:", counts)
        assert counts and counts[2] != "0" and counts[3] != "0", "SPA 进工作台数据为空"

        # compact 模式下演绎条照样在结果区上方，不必展开输入面板
        # （展开会撞上 grid 布局过渡的中间态，拍到错乱画面）

        # 3) 演绎：点第 3 步（关系）与第 4 步（回到原文），抓两个真实中间态
        steps = pg.locator(".replay-step")
        print("replay steps:", steps.count())
        assert steps.count() == 4
        steps.nth(2).click()
        pg.wait_for_timeout(350)
        shot(pg, "43-replay-stage-relations.png")
        assert pg.locator(".replay-triple-list li").count() > 0

        steps.nth(3).click()
        pg.wait_for_timeout(350)
        shot(pg, "44-replay-stage-evidence.png")
        assert "触发词" in pg.locator(".replay-evidence").inner_text()

        # 4) 播放按钮走完四阶段，末态是「回到原文」
        pg.get_by_role("button", name="播放抽取过程").click()
        pg.wait_for_timeout(1300)
        assert pg.locator(".replay-step.is-active").inner_text().strip().endswith("回到原文")
        print("full play reached final stage")

        # 5) 390 窄屏：首页 + 演绎
        mobile = browser.new_page(viewport={"width": 390, "height": 844})
        mobile.goto(BASE, wait_until="networkidle")
        mobile.wait_for_timeout(500)
        mobile.get_by_role("link", name="进入工作台").first.click()
        mobile.wait_for_url("**/app")
        mobile.wait_for_timeout(1500)
        msteps = mobile.locator(".replay-step")
        if msteps.count() == 4:
            msteps.nth(3).click()
            mobile.wait_for_timeout(350)
        shot(mobile, "45-replay-390.png")

        browser.close()


if __name__ == "__main__":
    main()
