# -*- coding: utf-8 -*-
"""接口层回归测试。

只覆盖「改坏了会悄悄出事」的那几条：输入校验、编码识别、历史记录读写、
静态资源边界。NLP 精度本身由 eval/gold.json 那套评测负责。
"""

from __future__ import annotations

import pytest

from app.samples import SAMPLES

SAMPLE_TEXT = SAMPLES[0]["content"]


# ---------- 基本可用 ----------


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_schema_lists_all_relation_types(client):
    r = client.get("/api/schema")
    assert r.status_code == 200
    data = r.json()
    assert len(data["entity_types"]) == 6
    assert data["relation_count"] == len(data["relation_types"]) == 19


def test_extract_text_returns_result_and_record(client):
    r = client.post("/api/extract", json={"text": SAMPLE_TEXT, "save": True})
    assert r.status_code == 200
    data = r.json()
    assert data["record_id"] is not None
    stats = data["result"]["stats"]
    # 内置示例的基线结果，词典/规则被改动时会在这里先炸
    assert stats["entity_count"] == 18
    assert stats["relation_count"] == 9
    assert len(data["result"]["sentences"]) == stats["sentence_count"]


def test_extract_without_save_does_not_touch_history(client):
    r = client.post("/api/extract", json={"text": SAMPLE_TEXT, "save": False})
    assert r.json()["record_id"] is None
    assert client.get("/api/records").json()["total"] == 0


# ---------- 输入校验 ----------


def test_extract_rejects_empty_text(client):
    r = client.post("/api/extract", json={"text": "   "})
    assert r.status_code == 400
    assert "空" in r.json()["detail"]


def test_extract_rejects_too_long_text(client):
    r = client.post("/api/extract", json={"text": "腾" * 20001})
    assert r.status_code == 413


def test_upload_rejects_unknown_extension(client):
    files = {"file": ("note.pdf", b"%PDF-1.4", "application/pdf")}
    r = client.post("/api/extract/file", files=files)
    assert r.status_code == 415


@pytest.mark.parametrize(
    ("encoding", "payload"),
    [
        ("utf-8", "腾讯控股收购搜狗公司，总金额约 35 亿美元。"),
        ("gbk", "腾讯控股收购搜狗公司，总金额约 35 亿美元。"),
        ("big5", "台灣積體電路製造公司收購矽品精密工業，總部位於新竹。"),
        ("utf-16", "腾讯控股收购搜狗公司，总金额约 35 亿美元。"),
    ],
)
def test_upload_decodes_legacy_encodings(client, encoding, payload):
    """gb18030 能解开任何字节，所以必须靠打分挑编码，不能"第一个不报错就用"。"""
    files = {"file": ("news.txt", payload.encode(encoding), "text/plain")}
    r = client.post("/api/extract/file?save=false", files=files)
    assert r.status_code == 200
    assert r.json()["result"]["text"] == payload


# ---------- 历史记录 ----------


def test_record_roundtrip(client):
    record_id = client.post("/api/extract", json={"text": SAMPLE_TEXT}).json()["record_id"]

    detail = client.get(f"/api/records/{record_id}").json()
    assert detail["relation_count"] == 9
    assert len(detail["relations"]) == 9
    # 归一化字段必须落库，否则图谱与统计会拆成两个节点
    assert detail["relations"][0]["head_canonical"]

    assert client.delete(f"/api/records/{record_id}").json()["ok"] is True
    assert client.get(f"/api/records/{record_id}").status_code == 404
    assert client.get("/api/stats").json()["records"] == 0


def test_missing_record_returns_404(client):
    assert client.get("/api/records/999999").status_code == 404
    assert client.delete("/api/records/999999").status_code == 404


def test_records_keyword_search(client):
    client.post("/api/extract", json={"text": SAMPLE_TEXT, "title": "腾讯收购搜狗"})
    client.post("/api/extract", json={"text": SAMPLES[1]["content"], "title": "阿里收购饿了么"})
    hit = client.get("/api/records", params={"keyword": "搜狗"}).json()
    assert hit["total"] == 1
    assert hit["items"][0]["title"] == "腾讯收购搜狗"


# ---------- 静态资源边界 ----------


def test_static_route_does_not_leak_outside_dist(client):
    """路径穿越：插件/工具常拿这个探源码和数据库。"""
    for path in ("/..%2f..%2fbackend%2fapp%2fdb.py", "/..%2f..%2fREADME.md"):
        r = client.get(path)
        body = r.content
        assert b"SQLite" not in body, f"{path} 泄露了后端源码"
        assert b"# \xe4\xb8\xad\xe6\x96\x87\xe5\x85\xb3\xe7\xb3\xbb" not in body, f"{path} 泄露了 README"


def test_spa_fallback_still_serves_index(client):
    r = client.get("/entities")
    assert r.status_code == 200
    assert b"<div id=\"app\">" in r.content or b"<!DOCTYPE html>" in r.content
