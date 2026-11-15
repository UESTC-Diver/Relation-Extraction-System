# -*- coding: utf-8 -*-
"""P1 功能回归测试：自定义词典、快照保存、人工校正。"""

from __future__ import annotations

import pytest

from app.samples import SAMPLES

SAMPLE_TEXT = SAMPLES[0]["content"]


def _extract(client, text: str) -> dict:
    r = client.post("/api/extract", json={"text": text, "save": False})
    assert r.status_code == 200
    return r.json()["result"]


def _snapshot(client, result: dict, title: str = "校正测试") -> int:
    r = client.post("/api/records", json={"title": title, "result": result})
    assert r.status_code == 200
    return r.json()["record_id"]


# ---------- 自定义词典 ----------


def test_dictionary_crud_and_custom_extraction(client):
    assert client.get("/api/dictionary").json()["total"] == 0

    r = client.post("/api/dictionary", json={"text": "星河科技", "type": "ORG"})
    assert r.status_code == 200
    term = r.json()
    assert term["text"] == "星河科技"
    assert term["type"] == "ORG"

    duplicate = client.post("/api/dictionary", json={"text": "星河科技", "type": "ORG"}).json()
    assert duplicate["duplicate"] is True
    assert client.get("/api/dictionary").json()["total"] == 1

    result = _extract(client, "星河科技与华为签署战略合作协议。")
    custom = [e for e in result["entities"] if e["source"] == "custom"]
    assert any(e["text"] == "星河科技" for e in custom)
    assert any(rel["head"] == "星河科技" for rel in result["relations"])

    assert client.delete(f"/api/dictionary/{term['id']}").json()["ok"] is True
    assert client.delete(f"/api/dictionary/{term['id']}").status_code == 404
    assert client.get("/api/dictionary").json()["total"] == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"text": "星", "type": "ORG"},          # 少于 2 个字符
        {"text": "星河科技", "type": "ALIEN"},  # 未知实体类型
    ],
)
def test_dictionary_rejects_invalid_terms(client, payload):
    assert client.post("/api/dictionary", json=payload).status_code == 400


def test_dictionary_clear(client):
    client.post("/api/dictionary", json={"text": "星河科技", "type": "ORG"})
    client.post("/api/dictionary", json={"text": "云舟资本", "type": "ORG"})
    removed = client.delete("/api/dictionary").json()
    assert removed["ok"] is True
    assert removed["removed"] == 2
    assert client.get("/api/dictionary").json()["total"] == 0


# ---------- 快照保存 ----------


def test_snapshot_roundtrip_and_invalid_payloads(client):
    result = _extract(client, SAMPLE_TEXT)
    record_id = _snapshot(client, result)

    detail = client.get(f"/api/records/{record_id}").json()
    assert detail["title"] == "校正测试"
    assert detail["relation_count"] == len(result["relations"])
    assert len(detail["relations"]) == len(result["relations"])

    empty = client.post("/api/records", json={"result": {"text": "   "}})
    assert empty.status_code == 400

    bad = _extract(client, SAMPLE_TEXT)
    bad["relations"][0]["relation"] = "not_a_relation"
    assert client.post("/api/records", json={"result": bad}).status_code == 400


# ---------- 人工校正 ----------


def test_manual_correction_roundtrip(client):
    result = _extract(client, SAMPLE_TEXT)
    record_id = _snapshot(client, result)
    detail = client.get(f"/api/records/{record_id}").json()

    manual = {
        "head": "腾讯控股有限公司",
        "head_type": "ORG",
        "relation": "compete",
        "tail": "星河科技",
        "tail_type": "ORG",
        "confidence": 1.0,
        "evidence": "腾讯控股有限公司与星河科技存在竞争。",
        "trigger": "人工校正",
        "sentence_index": None,
        "rule_base": "manual",
    }
    relations = detail["relations"] + [manual]
    r = client.put(f"/api/records/{record_id}/relations", json={"relations": relations})
    assert r.status_code == 200
    updated = r.json()
    assert updated["relation_count"] == len(relations)

    saved = next(item for item in updated["relations"] if item["rule_base"] == "manual")
    assert saved["head_canonical"] == "腾讯"
    assert saved["tail_canonical"] == "星河科技"
    assert saved["sentence_index"] == -1  # null 表示未指定证据句，落库为 -1

    again = client.get(f"/api/records/{record_id}").json()
    assert again["relation_count"] == len(relations)
    assert any(item["rule_base"] == "manual" for item in again["relations"])


def test_correction_persists_entity_snapshot(client):
    """人工新增关系时带入的实体也要写回 records，记录列表的实体数不能是旧值。"""
    result = _extract(client, SAMPLE_TEXT)
    record_id = _snapshot(client, result)
    detail = client.get(f"/api/records/{record_id}").json()

    manual_entity = {
        "id": "manual-e1",
        "text": "星河科技",
        "canonical": "星河科技",
        "type": "ORG",
        "type_label": "组织机构",
        "color": "#0ea5e9",
        "start": 0,
        "end": 4,
        "sentence_index": -1,
        "source": "manual",
        "confidence": 1,
    }
    manual_relation = {
        "head": "腾讯控股",
        "head_type": "ORG",
        "relation": "compete",
        "tail": "星河科技",
        "tail_type": "ORG",
        "confidence": 1.0,
        "evidence": "",
        "trigger": "人工校正",
        "sentence_index": -1,
        "rule_base": "manual",
    }
    r = client.put(
        f"/api/records/{record_id}/relations",
        json={
            "relations": detail["relations"] + [manual_relation],
            "entities": detail["entities"] + [manual_entity],
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["entity_count"] == len(detail["entities"]) + 1
    assert any(e.get("source") == "manual" for e in data["entities"])

    again = client.get(f"/api/records/{record_id}").json()
    assert again["entity_count"] == data["entity_count"]
    assert any(e["text"] == "星河科技" for e in again["entities"])


def test_manual_correction_rejects_invalid_relations(client):
    result = _extract(client, SAMPLE_TEXT)
    record_id = _snapshot(client, result)
    detail = client.get(f"/api/records/{record_id}").json()

    bad = dict(detail["relations"][0])
    bad["relation"] = "not_a_relation"
    assert client.put(f"/api/records/{record_id}/relations", json={"relations": [bad]}).status_code == 400

    empty_fields = {"head": "", "head_type": "ORG", "relation": "acquire", "tail": "搜狗", "tail_type": "ORG"}
    assert client.put(
        f"/api/records/{record_id}/relations", json={"relations": [empty_fields]}
    ).status_code == 400

    assert client.put("/api/records/999999/relations", json={"relations": []}).status_code == 404


def test_manual_correction_can_clear_all_relations(client):
    result = _extract(client, SAMPLE_TEXT)
    record_id = _snapshot(client, result)
    r = client.put(f"/api/records/{record_id}/relations", json={"relations": []})
    assert r.status_code == 200
    assert r.json()["relation_count"] == 0
    assert client.get(f"/api/records/{record_id}").json()["relations"] == []
