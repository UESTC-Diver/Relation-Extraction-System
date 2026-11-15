# -*- coding: utf-8 -*-
"""第二批 / 第三批能力的回归测试。

覆盖：FTS5 中文子串检索与降级路径、增量统计一致性、批量抽取与聚合、
自定义关系触发词的热生效、健康检查字段、静态与写保护边界。
"""

from __future__ import annotations

import pytest

from app import db
from app.samples import SAMPLES

TEXT_A = "腾讯控股宣布收购搜狗公司，搜狗将成为腾讯控股的全资子公司。"
TEXT_B = "阿里巴巴集团投资饿了么公司，双方签署战略合作协议。"


# ---------- 全文检索 ----------

def test_fts5_chinese_substring_search(client):
    client.post("/api/extract", json={"text": TEXT_A, "title": "腾讯收购搜狗"})
    client.post("/api/extract", json={"text": TEXT_B, "title": "阿里投资饿了么"})
    # 4 字关键词走 trigram MATCH；2 字关键词回退 LIKE，两条路径结果一致
    for keyword, expected in [("搜狗公司", 1), ("战略合作协议", 1), ("搜狗", 1)]:
        hit = client.get("/api/records", params={"keyword": keyword}).json()
        assert hit["total"] == expected, keyword
    assert client.get("/api/records", params={"keyword": "完全不存在的词"}).json()["total"] == 0


def test_search_with_fts_metacharacters_still_works(client):
    client.post("/api/extract", json={"text": TEXT_A, "title": "腾讯收购搜狗"})
    # 含 FTS 语法字符时不能让整次搜索抛 500
    r = client.get("/api/records", params={"keyword": '" OR * '})
    assert r.status_code == 200


# ---------- 增量统计 ----------

def _truth():
    with db.connect() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS records,
                      COALESCE(SUM(char_count), 0) AS chars,
                      COALESCE(SUM(entity_count), 0) AS entities,
                      COALESCE(SUM(relation_count), 0) AS relations
               FROM records"""
        ).fetchone()
    return dict(row)


def test_counters_stay_in_sync_through_writes(client):
    r1 = client.post("/api/extract", json={"text": TEXT_A}).json()["record_id"]
    client.post("/api/extract", json={"text": TEXT_B})
    stats = client.get("/api/stats").json()
    truth = _truth()
    assert (stats["records"], stats["relations"], stats["chars"]) == (
        truth["records"], truth["relations"], truth["chars"]
    )

    # 人工校正把关系清空：计数要跟着减，而不是等 5 秒缓存过期才对
    client.put(f"/api/records/{r1}/relations", json={"relations": []})
    assert client.get("/api/stats").json()["relations"] == _truth()["relations"]

    client.delete(f"/api/records/{r1}")
    stats = client.get("/api/stats").json()
    assert stats["records"] == _truth()["records"] == 1
    assert stats["relations"] == _truth()["relations"]

    client.delete("/api/records")
    assert client.get("/api/stats").json()["records"] == 0
    assert _truth()["records"] == 0


# ---------- 批量抽取 ----------

def test_batch_text_returns_items_and_aggregate(client):
    r = client.post(
        "/api/extract/batch",
        json={"items": [{"text": TEXT_A, "title": "A"}, {"text": TEXT_B, "title": "B"}], "save": True},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == data["succeeded"] == 2
    assert data["failed"] == 0
    assert all(item["record_id"] for item in data["items"])
    assert data["aggregate"]["records"] == 2
    assert data["aggregate"]["relations"] == sum(i["relation_count"] for i in data["items"])
    assert len(data["aggregate"]["top_entities"]) > 0


def test_batch_without_save_aggregates_in_memory(client):
    r = client.post(
        "/api/extract/batch",
        json={"items": [{"text": TEXT_A}, {"text": TEXT_B}], "save": False},
    )
    data = r.json()
    assert data["succeeded"] == 2
    assert all(item["record_id"] is None for item in data["items"])
    assert data["aggregate"]["records"] == 2
    assert client.get("/api/records").json()["total"] == 0


def test_batch_single_failure_does_not_break_others(client):
    r = client.post(
        "/api/extract/batch",
        json={"items": [{"text": " "}, {"text": TEXT_A, "title": "A"}], "save": False},
    )
    data = r.json()
    assert data["total"] == 2 and data["succeeded"] == 1 and data["failed"] == 1
    assert data["items"][0]["error"]
    assert data["items"][1]["error"] is None


def test_batch_files_decodes_mixed_encodings(client):
    files = [
        ("files", ("a.txt", TEXT_A.encode("utf-8"), "text/plain")),
        ("files", ("b.md", TEXT_B.encode("gbk"), "text/plain")),
    ]
    r = client.post("/api/extract/batch/files?save=false", files=files)
    assert r.status_code == 200
    assert r.json()["succeeded"] == 2


def test_batch_rejects_too_many_items(client):
    payload = {"items": [{"text": TEXT_A} for _ in range(21)], "save": False}
    assert client.post("/api/extract/batch", json=payload).status_code == 422


# ---------- 自定义关系触发词 ----------

@pytest.fixture()
def cleanup_rules(client):
    yield client
    client.delete("/api/rules")


def test_custom_trigger_takes_effect_without_restart(cleanup_rules):
    client = cleanup_rules
    sentence = "腾讯控股吃下搜狗公司。"
    before = client.post("/api/extract", json={"text": sentence, "save": False}).json()
    assert before["result"]["stats"]["relation_count"] == 0

    added = client.post("/api/rules", json={"relation_key": "acquire", "trigger": "吃下"})
    assert added.status_code == 200
    after = client.post("/api/extract", json={"text": sentence, "save": False}).json()
    assert any(r["relation"] == "acquire" for r in after["result"]["relations"])

    # 目录仍然是 19 类，自定义触发词不会新增关系类型
    assert client.get("/api/schema").json()["relation_count"] == 19

    client.delete(f"/api/rules/{added.json()['id']}")
    restored = client.post("/api/extract", json={"text": sentence, "save": False}).json()
    assert restored["result"]["stats"]["relation_count"] == 0


def test_rules_validation(cleanup_rules):
    client = cleanup_rules
    assert client.post("/api/rules", json={"relation_key": "nope", "trigger": "吃下"}).status_code == 400
    assert client.post("/api/rules", json={"relation_key": "acquire", "trigger": "收购"}).status_code == 400
    assert client.post("/api/rules", json={"relation_key": "acquire", "trigger": "a b"}).status_code == 400
    created = client.post("/api/rules", json={"relation_key": "invest", "trigger": "战略注资"}).json()
    listing = client.get("/api/rules").json()
    assert listing["total"] == 1
    assert len(listing["relation_types"]) == 19
    assert any(t["key"] == "invest" and t["triggers"] for t in listing["relation_types"])
    assert client.delete(f"/api/rules/{created['id']}").json()["ok"] is True


# ---------- 健康信息 / 快照校正 ----------

def test_health_reports_runtime_details(client):
    data = client.get("/api/health").json()
    assert data["status"] == "ok"
    assert data["relation_types"] == 19
    assert data["version"]
    assert data["full_text_search"] is True
    assert data["max_concurrent_extract"] >= 1
    assert "db_size_bytes" in data


def test_save_snapshot_with_manual_relations(client):
    result = client.post("/api/extract", json={"text": TEXT_A, "save": False}).json()["result"]
    result["relations"] = [{
        "head": "腾讯控股", "head_type": "ORG", "relation": "acquire",
        "tail": "搜狗公司", "tail_type": "ORG", "confidence": 1.0,
        "evidence": TEXT_A, "trigger": "人工校正", "rule_base": "manual",
    }]
    r = client.post("/api/records", json={"title": "校正副本", "result": result})
    assert r.status_code == 200
    detail = client.get(f"/api/records/{r.json()['record_id']}").json()
    assert detail["relation_count"] == 1
    assert detail["relations"][0]["rule_base"] == "manual"
