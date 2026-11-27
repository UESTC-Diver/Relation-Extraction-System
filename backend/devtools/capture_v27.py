# -*- coding: utf-8 -*-
"""v2.7.0 真出图：断言极性标记 + 非事实筛选 + 评测台新基线（桌面/390）。

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

# 一段同时含「事实」「否认」「传闻」的文本——正是极性判定要区分的场景
SAMPLE = (
    "9月5日，腾讯控股宣布以35亿美元收购搜狗公司全部流通股。"
    "交易完成后，搜狗将成为腾讯控股的全资子公司。"
    "针对近日传闻，腾讯控股今日发布声明，明确否认收购字节跳动的短视频业务。"
    "有媒体报道称腾讯将收购另一家搜索企业，但双方均未证实这一消息。"
)


def shot(pg, name):
    path = OUT / name
    pg.screenshot(path=str(path))
    overflow = pg.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    print(f"{name}: saved, horizontal overflow = {overflow}px")


def fill_and_extract(pg):
    """填入混合文本并抽取；返回结果里各断言档位的计数。"""
    pg.goto(f"{BASE}/app", wait_until="networkidle")
    pg.wait_for_timeout(1200)
    # 工作台默认 compact，展开编辑面板
    edit = pg.locator(".cp-edit")
    if edit.count():
        edit.first.click()
        pg.wait_for_timeout(400)
    box = pg.locator(".wb-textarea textarea").first
    box.fill(SAMPLE)
    pg.get_by_role("button", name="开始抽取").click()
    pg.wait_for_timeout(2500)
    # 先切到三元组页签：断言标签只在表格里渲染
    tab = pg.get_by_role("tab", name="关系三元组")
    if tab.count():
        tab.first.click()
        pg.wait_for_timeout(600)
    pg.wait_for_selector(".assertion-tag", timeout=15000)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=EXE)

        # 1) 桌面：断言极性标记 + 筛选控件
        pg = browser.new_page(viewport={"width": 1440, "height": 900})
        fill_and_extract(pg)

        tags = pg.locator(".assertion-tag").all_inner_texts()
        print("assertion tags:", tags)
        assert tags, "没有渲染出断言标签"
        assert any("否认" in t or "传闻" in t for t in tags), tags

        seg = pg.locator(".assertion-seg")
        assert seg.count() == 1, "非事实筛选控件没出现"
        print("seg text:", seg.inner_text().replace("\n", " "))

        shot(pg, "46-assertion-tags.png")

        # 2) 只看非事实：确认筛选真的生效
        seg.get_by_role("button", name="仅非事实").click()
        pg.wait_for_timeout(500)
        rows = pg.locator(".el-table__row")
        print("non-fact rows:", rows.count())
        assert rows.count() >= 1
        shot(pg, "47-assertion-only-nonfact.png")

        # 3) 评测台：新金标准基线
        pg.get_by_role("button", name="更多功能").click()
        pg.get_by_text("效果评测").click()
        pg.wait_for_timeout(800)
        pg.get_by_role("button", name="运行评测").first.click()
        pg.wait_for_timeout(3500)
        text = pg.locator(".el-dialog").last.inner_text()
        assert "0.89" in text or "89" in text, text[:300]
        shot(pg, "48-eval-new-baseline.png")
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(400)

        # 4) 390 窄屏：滚到三元组工具栏，让筛选与标记都落在视口里
        mobile = browser.new_page(viewport={"width": 390, "height": 844})
        fill_and_extract(mobile)
        mobile.wait_for_timeout(3200)  # 等完成提示条自动消失，避免压住页头
        # 让筛选组贴顶，表格首行紧随其下，一屏内同时看到控件与标记
        mobile.evaluate(
            "document.querySelector('.assertion-seg').scrollIntoView({block: 'start'})"
        )
        mobile.wait_for_timeout(400)
        shot(mobile, "49-assertion-390.png")

        browser.close()


if __name__ == "__main__":
    main()
