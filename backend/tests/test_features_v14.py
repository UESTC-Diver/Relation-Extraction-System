# -*- coding: utf-8 -*-
"""1.4.0 回归测试：上线最小安全集与复核 → 定稿 → 分享闭环。"""

from __future__ import annotations

import pytest

from app import db, security
from app.samples import SAMPLES

TEXT = SAMPLES[0]["content"]


def seed(client):
    r = client.post("/api/extract", json={"text": TEXT, "title": "复核用例", "save": True})
    assert r.status_code == 200, r.text
    return r.json()["record_id"]


def decide(client, rid, key, decision="approved", note="证据句吻合"):
    return client.put(
        f"/api/records/{rid}/review/decisions",
        json={"decisions": [{"relation_key": key, "decision": decision, "note": note}]},
    )


def test_health_version_and_cors_default(client):
    assert client.get("/api/health").json()["version"] == "1.5.0"
    # 默认白名单不含 *，陌生来源拿不到 CORS 放行头
    res = client.options(
        "/api/extract",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in res.headers


def test_review_state_starts_as_draft(client):
    rid = seed(client)
    state = client.get(f"/api/records/{rid}/review").json()
    assert state["status"] == "draft"
    assert state["editable"] is True
    assert state["summary"]["total"] > 0
    assert state["summary"]["reviewed"] == 0
    assert all(r["review_key"] for r in state["relations"])


def test_save_decisions_and_summary(client):
    rid = seed(client)
    state = client.get(f"/api/records/{rid}/review").json()
    keys = [r["review_key"] for r in state["relations"][:2]]
    res = client.put(
        f"/api/records/{rid}/review/decisions",
        json={
            "decisions": [
                {"relation_key": keys[0], "decision": "approved", "note": "证据句吻合"},
                {"relation_key": keys[1], "decision": "questioned", "note": "实体边界存疑"},
            ],
            "reviewer": "复核员",
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["summary"]["approved"] == 1
    assert body["summary"]["questioned"] == 1
    assert body["summary"]["reviewed"] == 2
    assert body["relations"][0]["review_note"] == "证据句吻合"


def test_status_flow_requires_finalize(client):
    rid = seed(client)
    url = f"/api/records/{rid}/review/status"
    assert client.put(url, json={"status": "unknown"}).status_code == 400
    assert client.put(url, json={"status": "final"}).status_code == 409
    assert client.put(url, json={"status": "in_review"}).json()["status"] == "in_review"
    assert client.put(url, json={"status": "draft"}).json()["status"] == "draft"


def test_finalize_locks_edits_and_writes_snapshot(client):
    rid = seed(client)
    state = client.get(f"/api/records/{rid}/review").json()
    assert decide(client, rid, state["relations"][0]["review_key"]).status_code == 200
    out = client.post(f"/api/records/{rid}/review/finalize", json={"title": "定稿 v1"})
    assert out.status_code == 200, out.text
    assert out.json()["snapshot_id"] > 0
    assert out.json()["status"] == "final"
    assert out.json()["editable"] is False

    assert client.put(f"/api/records/{rid}/relations", json={"relations": []}).status_code == 409
    assert client.put(f"/api/records/{rid}/entities", json={"entities": []}).status_code == 409
    assert client.put(
        f"/api/records/{rid}/review/decisions", json={"decisions": []}
    ).status_code == 409

    snaps = client.get(f"/api/records/{rid}/review/snapshots").json()
    assert snaps["total"] == 1
    detail = client.get(
        f"/api/records/{rid}/review/snapshots/{snaps['items'][0]['id']}"
    ).json()
    assert detail["relations"] and detail["decisions"]

    # 解锁退回 in_review 后才能继续改稿
    assert client.put(
        f"/api/records/{rid}/review/status", json={"status": "in_review"}
    ).json()["status"] == "in_review"
    assert client.put(f"/api/records/{rid}/relations", json={"relations": []}).status_code == 200


def test_report_includes_review_section_and_readonly_headers(client):
    rid = seed(client)
    state = client.get(f"/api/records/{rid}/review").json()
    assert decide(client, rid, state["relations"][0]["review_key"]).status_code == 200
    file = client.post("/api/report", json={"record_id": rid}).json()
    assert "复核结论" in file["html"]
    assert "通过" in file["html"]
    assert "<script" not in file["html"].lower()

    page = client.get(f"/report/{rid}")
    assert page.status_code == 200
    assert page.headers["x-robots-tag"] == "noindex, nofollow"
    assert "private" in page.headers["cache-control"]
    assert "复核结论" in page.text


def test_share_link_signature_enforced_mode(client, monkeypatch):
    monkeypatch.setenv("APP_REPORT_SECRET", "test-secret-key")
    rid = seed(client)
    res = client.post("/api/report/share", json={"record_id": rid, "ttl_seconds": 3600})
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["signed"] is True and data["enforced"] is True
    assert "token=" in data["url"] and "expires=" in data["url"]

    assert client.get(f"/report/{rid}").status_code == 403
    signed = data["url"].split("/report/", 1)[1]
    assert client.get(f"/report/{signed}").status_code == 200
    assert client.get(f"/report/{rid}", params={"expires": "1", "token": "bad"}).status_code == 403


def test_body_size_limit(client, monkeypatch):
    monkeypatch.setenv("APP_MAX_BODY_BYTES", "1024")
    r = client.post("/api/extract", json={"text": "腾讯" * 500, "save": False})
    assert r.status_code == 413


def test_rate_limit_per_ip(client, monkeypatch):
    monkeypatch.setenv("APP_RATE_LIMIT_PER_MIN", "2")
    security.limiter._hits.clear()
    codes = [client.get("/api/health").status_code for _ in range(4)]
    assert codes[:2] == [200, 200]
    assert 429 in codes
    security.limiter._hits.clear()


def test_upload_rejects_forged_magic_bytes(client):
    r = client.post(
        "/api/extract/file?save=false",
        files={"file": ("fake.pdf", b"this is not a pdf", "application/pdf")},
    )
    assert r.status_code == 400
    assert "不是有效的 PDF" in r.json()["detail"]
    r = client.post(
        "/api/extract/file?save=false",
        files={"file": ("fake.docx", b"not a zip", "application/octet-stream")},
    )
    assert r.status_code == 400
    assert "不是有效的 DOCX" in r.json()["detail"]


def test_pdf_page_ceiling(client):
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    for _ in range(61):
        doc.new_page().insert_text((50, 50), "hello")
    payload = doc.tobytes()
    doc.close()
    r = client.post(
        "/api/extract/file?save=false",
        files={"file": ("many.pdf", payload, "application/pdf")},
    )
    assert r.status_code == 413
    assert "页数过多" in r.json()["detail"]


def test_cleanup_removes_review_rows(client):
    rid = seed(client)
    state = client.get(f"/api/records/{rid}/review").json()
    assert decide(client, rid, state["relations"][0]["review_key"]).status_code == 200
    assert client.post(f"/api/records/{rid}/review/finalize", json={}).status_code == 200
    assert client.delete(f"/api/records/{rid}").status_code == 200
    seed(client)
    assert client.delete("/api/records").status_code == 200
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM review_decisions").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM review_snapshots").fetchone()[0] == 0
