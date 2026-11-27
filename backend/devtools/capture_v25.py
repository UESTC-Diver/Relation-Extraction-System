# -*- coding: utf-8 -*-
"""v2.5.0 真出图：首页价值段 / 工作台语言切换 / 双引擎对话框，桌面 + 390。"""
from __future__ import annotations

import os
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)
BASE = "http://127.0.0.1:8000"
EXE = os.path.join(
    os.environ["LOCALAPPDATA"], "ms-playwright", "chromium-1248", "chrome-win64", "chrome.exe"
)


def snap(page, name: str, url: str, width: int, height: int, actions=None):
    page.set_viewport_size({"width": width, "height": height})
    page.goto(BASE + url, wait_until="networkidle")
    if actions:
        actions(page)
    page.wait_for_timeout(800)
    path = OUT / name
    page.screenshot(path=str(path), full_page=False)
    print("saved", path.name)


def open_engine_dialog(page):
    # 工作台可能处于 compact 模式：有 .cp-edit 时先展开编辑面板
    edit = page.locator(".cp-edit")
    if edit.count():
        edit.first.click()
        page.wait_for_timeout(300)
    more = page.get_by_role("button", name="更多功能")
    more.click()
    page.get_by_text("双引擎对比").click()
    page.wait_for_timeout(1200)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=EXE)
    page = browser.new_page()

    snap(page, "36-landing-closing-svg.png", "/", 1440, 900,
         lambda pg: pg.locator("#closing").scroll_into_view_if_needed())
    snap(page, "37-landing-closing-390.png", "/", 390, 844,
         lambda pg: pg.locator("#closing").scroll_into_view_if_needed())
    snap(page, "38-workbench-auto-lang.png", "/app", 1440, 900)
    snap(page, "39-workbench-auto-lang-390.png", "/app", 390, 844)
    snap(page, "40-engine-compare.png", "/app", 1440, 900, open_engine_dialog)
    snap(page, "41-engine-compare-390.png", "/app", 390, 844, open_engine_dialog)

    browser.close()
