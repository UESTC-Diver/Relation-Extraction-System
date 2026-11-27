# -*- coding: utf-8 -*-
"""2.6.0：页面转场 + 抽取过程演绎的前端交付，后端侧保证版本与 SPA 路由回归。"""

from __future__ import annotations

import re

from app import main


def test_version_bumped(client):
    assert re.match(r"^2\.6\.\d+$", main.VERSION)
    health = client.get("/api/health").json()
    assert health["version"] == main.VERSION == "2.6.0"


def test_spa_routes_still_serve_index(client):
    """页面转场依赖每个路由都回落到同一个 index.html，否则 SPA 导航会白屏。"""
    index = client.get("/").text
    assert '<div id="app"></div>' in index
    for path in ("/app", "/demo", "/cases", "/verify", "/some-unknown-path"):
        resp = client.get(path)
        assert resp.status_code == 200
        assert '<div id="app"></div>' in resp.text


def test_frontend_assets_present(client):
    """新组件和转场样式必须真的进了构建产物，避免只改了 src 没重建 dist。"""
    index = client.get("/").text
    assets = re.findall(r'(?:src|href)="([^"]+\.(?:js|css))"', index)
    assert assets
    for asset in assets:
        resp = client.get(asset)
        assert resp.status_code == 200, asset
