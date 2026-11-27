# -*- coding: utf-8 -*-
"""1.3.0 新增能力的回归测试：知识库、质量闭环、交付与集成。"""

from __future__ import annotations

import io
import time

import pytest

TEXT_A = "腾讯控股宣布收购搜狗公司，搜狗将成为腾讯控股的全资子公司。"
TEXT_B = "阿里巴巴集团投资饿了么公司，双方签署战略合作协议。"


def seed(client, texts=(TEXT_A, TEXT_B)):
    ids = []
    for i, text in enumerate(texts):
        r = client.post("/api/extract", json={"text": text, "title": f"文档{i + 1}", "save": True})
        assert r.status_code == 200
        ids.append(r.json()["record_id"])
    return ids


def test_health_reports_new_version(client):
    from app.main import VERSION

    data = client.get("/api/health").json()
    assert data["version"] == VERSION
    assert data["status"] == "ok"


def test_global_entities_and_profile(client):
    seed(client)
    found = client.get("/api/entities", params={"q": "腾讯"}).json()
    assert found["total"] >= 1
    assert any(item["name"] == "腾讯" and item["documents"] >= 1 for item in found["items"])

    profile = client.get("/api/entities/profile", params={"name": "腾讯"}).json()
    assert profile["appearances"] >= 1
    assert "腾讯控股" in profile["aliases"]
    assert profile["documents"] and profile["relations"]


def test_global_graph_merges_documents(client):
    seed(client)
    graph = client.get("/api/graph/global").json()
    assert graph["node_count"] >= 2
    assert graph["link_count"] >= 1
    assert all("source" in link and "target" in link for link in graph["links"])


def test_tags_set_and_filter(client):
    rid = seed(client, (TEXT_A,))[0]
    r = client.put(f"/api/records/{rid}/tags", json={"tags": ["并购", "互联网"]})
    assert r.status_code == 200 and r.json()["tags"] == ["并购", "互联网"]
    assert client.get("/api/tags").json()["total"] == 2
    listing = client.get("/api/records", params={"tag": "并购"}).json()
    assert listing["total"] == 1
    assert listing["items"][0]["tags"] == ["并购", "互联网"]
    assert client.get("/api/records", params={"tag": "不存在"}).json()["total"] == 0


def test_conflicts_detected_after_manual_correction(client):
    rid = seed(client, (TEXT_A,))[0]
    keys = [r["key"] for r in client.get("/api/schema").json()["relation_types"][:2]]
    rel = {
        "head": "腾讯控股", "head_type": "ORG", "relation": keys[0],
        "tail": "搜狗公司", "tail_type": "ORG", "confidence": 1.0,
        "evidence": TEXT_A,
    }
    other = {**rel, "relation": keys[1]}
    assert client.put(f"/api/records/{rid}/relations", json={"relations": [rel, other]}).status_code == 200
    conflicts = client.get("/api/conflicts").json()
    assert conflicts["total"] >= 1
    assert any(len({i["relation"] for i in c["items"]}) > 1 for c in conflicts["items"])


def test_review_queue_returns_low_confidence(client):
    seed(client, (TEXT_A,))
    queue = client.get("/api/review", params={"threshold": 1.0}).json()
    assert queue["total"] >= 1
    assert all(item["confidence"] < 1.0 for item in queue["items"])


def test_eval_endpoint_and_history(client):
    from app.nlp.evaluation import load_gold

    gold_total = len(load_gold())
    assert gold_total >= 30
    assert client.get("/api/eval/gold").json()["total"] == gold_total
    result = client.post("/api/eval", json={"save": True}).json()
    assert result["run_id"] is not None
    report = result["report"]
    assert report["cases"] == gold_total
    assert 0 <= report["f1"] <= 1
    assert "per_relation" in report and "misses" in report

    history = client.get("/api/eval/runs").json()
    assert history["total"] >= 1
    detail = client.get(f"/api/eval/runs/{result['run_id']}").json()
    assert detail["report"]["f1"] == report["f1"]
    assert client.get("/api/eval/runs/999999").status_code == 404


def test_eval_accepts_custom_cases(client):
    cases = [{
        "id": "custom-1", "title": "自测", "text": TEXT_A,
        "relations": [["腾讯控股", "acquire", "搜狗公司"]],
    }]
    report = client.post("/api/eval", json={"cases": cases, "save": False}).json()["report"]
    assert report["cases"] == 1
    assert report["gold_total"] == 1


def test_rules_trial_shows_added_relation(client):
    payload = {
        "text": "腾讯控股吃下搜狗公司。",
        "triggers": [{"relation_key": "acquire", "trigger": "吃下"}],
    }
    diff = client.post("/api/rules/trial", json=payload).json()
    assert diff["after_count"] > diff["before_count"]
    assert diff["added"]
    # 试跑不得污染真实配置
    assert client.get("/api/rules").json()["items"] == []
    assert client.post("/api/rules/trial", json={
        "text": TEXT_A, "triggers": [{"relation_key": "not_exist", "trigger": "x"}],
    }).status_code == 400


def test_rule_versions_save_and_restore(client):
    added = client.post("/api/rules", json={"relation_key": "acquire", "trigger": "战略吞并"})
    assert added.status_code == 200
    version = client.post("/api/rules/versions", json={"name": "基线A"}).json()
    assert client.get("/api/rules/versions").json()["total"] == 1

    client.delete(f"/api/rules/{added.json()['id']}")
    assert client.get("/api/rules").json()["total"] == 0
    restored = client.post(f"/api/rules/versions/{version['id']}/restore").json()
    assert restored["rules"] == 1
    assert client.get("/api/rules").json()["total"] == 1
    assert client.post("/api/rules/versions/999/restore").status_code == 404


def test_entity_correction_writes_back(client):
    rid = seed(client, (TEXT_A,))[0]
    record = client.get(f"/api/records/{rid}").json()
    entities = [{**e, "canonical": e.get("canonical") or e.get("text")} for e in record["entities"][:2]]
    assert entities
    r = client.put(f"/api/records/{rid}/entities", json={
        "entities": entities,
        "corrections": [{"original": entities[0]["text"], "corrected": entities[0]["canonical"], "type": "ORG"}],
    })
    assert r.status_code == 200
    assert r.json()["entity_count"] == len(entities)
    assert client.put(f"/api/records/{rid}/entities", json={
        "entities": [{"text": "x", "type": "BAD"}],
    }).status_code == 400


def test_report_is_single_offline_html(client):
    rid = seed(client, (TEXT_A,))[0]
    result = client.post("/api/report", json={"record_id": rid}).json()
    html = result["html"]
    assert html.startswith("<!DOCTYPE html>")
    assert "<style>" in html and "<script" not in html
    assert "http://" not in html and "https://" not in html
    assert "关系三元组与证据句" in html
    assert result["filename"].endswith(".html")
    assert client.post("/api/report", json={"record_id": 999999}).status_code == 404


def test_shared_report_page(client):
    rid = seed(client, (TEXT_A,))[0]
    page = client.get(f"/report/{rid}")
    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]
    assert "在工作台打开" in page.text
    assert client.get("/report/999999").status_code == 404


def test_project_export_and_merge_import(client):
    rid = seed(client, (TEXT_A,))[0]
    client.put(f"/api/records/{rid}/tags", json={"tags": ["并购"]})
    package = client.get("/api/project/export").json()
    assert package["format"] == "cn-re-project"
    assert len(package["records"]) == 1 and package["gold"]
    assert package["records"][0]["tags"] == "并购"

    imported = client.post("/api/project/import", json={"payload": package, "mode": "merge"}).json()
    assert imported["records"] == 1 and imported["relations"] >= 1
    assert client.get("/api/stats").json()["records"] == 2
    assert client.post("/api/project/import", json={"payload": {}, "mode": "merge"}).status_code == 400
    assert client.post("/api/project/import", json={
        "payload": package, "mode": "bad",
    }).status_code == 422


def test_project_replace_import(client):
    seed(client, (TEXT_A, TEXT_B))
    package = client.get("/api/project/export").json()
    replaced = client.post("/api/project/import", json={"payload": package, "mode": "replace"}).json()
    assert replaced["records"] == 2
    assert client.get("/api/stats").json()["records"] == 2


def test_background_batch_task(client):
    submitted = client.post("/api/tasks/batch", json={
        "items": [{"text": TEXT_A, "title": "A"}, {"text": TEXT_B, "title": "B"}],
        "save": True,
    })
    assert submitted.status_code == 200
    task_id = submitted.json()["task_id"]
    state = None
    for _ in range(60):
        state = client.get(f"/api/tasks/{task_id}").json()
        if state["status"] in ("done", "failed"):
            break
        time.sleep(0.2)
    assert state["status"] == "done", state
    assert state["done"] == 2 and state["result"]["succeeded"] == 2
    assert client.get("/api/tasks").json()["total"] >= 1
    assert client.get("/api/tasks/not-exist").status_code == 404


def test_pdf_upload(client):
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Tencent acquired Sogou.")
    raw = doc.tobytes()
    doc.close()
    r = client.post("/api/extract/file?save=false", files={"file": ("note.pdf", raw, "application/pdf")})
    assert r.status_code == 200, r.text
    assert "Tencent" in r.json()["result"]["text"]


def test_docx_upload(client):
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_paragraph("腾讯控股宣布收购搜狗公司。")
    buf = io.BytesIO()
    document.save(buf)
    r = client.post("/api/extract/file?save=false", files={
        "file": ("note.docx", buf.getvalue(), "application/octet-stream"),
    })
    assert r.status_code == 200, r.text
    assert "腾讯控股" in r.json()["result"]["text"]
