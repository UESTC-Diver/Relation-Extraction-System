# -*- coding: utf-8 -*-
"""pytest 公共夹具。

每个用例都用一个临时 SQLite 文件，互不干扰，也不会碰到 backend/data/app.db。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """把数据层指到临时目录后再启动应用。"""
    from app import db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)

    # 测试客户端所有请求都来自同一个 IP，一整套用例会超过生产限流额度；
    # 同时清掉本机可能残留的写保护 / 分享签名密钥，保证测试可重复。
    monkeypatch.setenv("APP_RATE_LIMIT_PER_MIN", "100000")
    monkeypatch.delenv("APP_API_TOKEN", raising=False)
    monkeypatch.delenv("APP_REPORT_SECRET", raising=False)

    from app.main import app

    with TestClient(app) as c:
        yield c
