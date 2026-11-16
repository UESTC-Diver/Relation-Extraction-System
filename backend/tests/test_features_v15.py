# -*- coding: utf-8 -*-
"""1.5.0 回归测试：可解释性、规则体检、领域包与静态试用数据。

默认 profile 必须与 1.4.0 逐字节等价，因此本文件的第一组断言专门守这条线：
新增字段不能改变三元组本身，也不能改变 F1。
"""

from __future__ import annotations

import json
from pathlib import Path

from app.nlp.pipeline import analyze
from app.nlp import profiles as domain_profiles

BASE_TEXT = "腾讯控股收购搜狗公司。"
FINANCE_TEXT = "腾讯控股吃下搜狗公司。"
LEGAL_TEXT = "腾讯控股仲裁字节跳动。"


# --------------------------------------------------------------------------- #
# 可解释性
# --------------------------------------------------------------------------- #

def test_explanation_attached_to_every_relation():
    result = analyze(FINANCE_TEXT, custom_triggers={"acquire": ["吃下"]})
    assert result["relations"]
    for rel in result["relations"]:
        exp = rel["explanation"]
        assert exp["strategy"]
        assert exp["strategy_how"]
        assert exp["matched"]
        assert "→" in exp["type_constraint"]
        assert exp["confidence_parts"]["exact"] is True
        assert exp["confidence_parts"]["base"] > 0
        assert "0.52" in exp["confidence_parts"]["formula"] or "0.98" in exp["confidence_parts"]["formula"]
        assert exp["evidence"] == rel["evidence"]
        assert len(exp["steps"]) == 4


def test_explanation_does_not_change_triples():
    """解释字段是纯展示，不能影响 head / relation / tail 三元组。"""
    baseline = analyze(FINANCE_TEXT, custom_triggers={"acquire": ["吃下"]})["relations"]
    assert baseline
    for rel in baseline:
        assert (rel["head"], rel["relation"], rel["tail"]) == (
            "腾讯控股", "acquire", "搜狗公司"
        )


def test_pattern_explanation_reports_template(client):
    res = client.post(
        "/api/extract",
        json={"text": "搜狗公司将成为腾讯控股的全资子公司。", "save": True},
    ).json()
    rel = next(r for r in res["result"]["relations"] if r["rule_base"] == "pattern")
    exp = rel["explanation"]
    assert exp["strategy"] == "句式模板"
    assert exp["template"] and "A" in exp["template"]
    assert exp["confidence_parts"]["exact"] is True
    assert exp["confidence_parts"]["base"] == 0.94


def test_historical_record_rebuilds_explanation(client):
    client.post("/api/extract", json={"text": BASE_TEXT, "save": True})
    detail = client.get("/api/records/1").json()
    assert detail["relations"]
    for rel in detail["relations"]:
        exp = rel["explanation"]
        assert exp["strategy"]
        # 历史快照只存结果字段，逐步分值明确标注为估算，不伪装精确
        assert exp["confidence_parts"]["exact"] is False
        assert "历史快照" in exp["confidence_parts"]["formula"]


def test_report_html_includes_explanation(client):
    client.post("/api/extract", json={"text": BASE_TEXT, "save": True})
    html = client.post("/api/report", json={"record_id": 1}).json()["html"]
    assert "为什么抽出来" in html
    assert "触发词" in html


# --------------------------------------------------------------------------- #
# 规则体检
# --------------------------------------------------------------------------- #

def test_insights_empty_state_is_honest(client):
    data = client.get("/api/insights").json()
    assert data["summary"]["relations"] == 0
    assert data["suggestions"]
    assert data["suggestions"][0]["kind"] == "baseline"
    assert data["hot_triggers"] == []


def test_insights_hot_triggers_and_unused(client):
    client.post("/api/extract", json={"text": BASE_TEXT, "save": True})
    data = client.get("/api/insights").json()
    assert data["summary"]["relations"] > 0
    assert data["hot_triggers"]
    assert data["hot_strategies"]
    assert data["hot_relations"]
    # 19 类里必然有从未在历史文本中出现的触发词
    assert data["summary"]["unused_triggers"] > 0
    assert all("trigger" in u and "relation_label" in u for u in data["unused_triggers"])
    assert any(s["kind"] in ("unused", "coverage") for s in data["suggestions"])


def test_insights_tracks_deleted_relations(client):
    client.post("/api/extract", json={"text": BASE_TEXT, "save": True})
    # 领域包抽出 1 条，人工删空它
    client.post(
        "/api/extract",
        json={"text": FINANCE_TEXT, "save": True, "profile": "finance"},
    )
    rec = client.get("/api/records/2").json()
    assert rec["relations"]
    dropped_relation = rec["relations"][0]["relation"]
    client.put("/api/records/2/relations", json={"relations": []})
    data = client.get("/api/insights").json()
    assert data["summary"]["deleted_relations"] == 1
    assert data["deleted_by_relation"][0]["relation"] == dropped_relation
    assert any(s["kind"] == "deleted" for s in data["suggestions"])


def test_insights_rejected_review_feeds_summary(client):
    client.post(
        "/api/extract",
        json={"text": FINANCE_TEXT, "save": True, "profile": "finance"},
    )
    state = client.get("/api/records/1/review").json()
    key = state["relations"][0]["review_key"]
    client.put(
        "/api/records/1/review/decisions",
        json={"decisions": [{"relation_key": key, "decision": "rejected"}]},
    )
    assert client.get("/api/insights").json()["summary"]["rejected"] == 1


# --------------------------------------------------------------------------- #
# 领域包
# --------------------------------------------------------------------------- #

def test_profiles_catalog_and_schema(client):
    data = client.get("/api/profiles").json()
    keys = [p["key"] for p in data["items"]]
    assert keys == ["general", "finance", "legal"]
    assert data["default"] == "general"
    general = next(p for p in data["items"] if p["key"] == "general")
    assert general["term_count"] == 0 and general["trigger_count"] == 0
    assert client.get("/api/schema").json()["default_profile"] == "general"
    assert "profiles" in client.get("/api/health").json()


def test_default_profile_equals_legacy_behavior(client):
    legacy = client.post("/api/extract", json={"text": FINANCE_TEXT, "save": False}).json()
    explicit = client.post(
        "/api/extract",
        json={"text": FINANCE_TEXT, "save": False, "profile": "general"},
    ).json()
    a = [(r["head"], r["relation"], r["tail"]) for r in legacy["result"]["relations"]]
    b = [(r["head"], r["relation"], r["tail"]) for r in explicit["result"]["relations"]]
    assert a == b
    assert explicit["result"]["profile"] == "general"


def test_finance_profile_adds_relations(client):
    base = client.post("/api/extract", json={"text": FINANCE_TEXT, "save": False}).json()
    rich = client.post(
        "/api/extract", json={"text": FINANCE_TEXT, "save": False, "profile": "finance"}
    ).json()
    assert base["result"]["relations"] == []
    assert rich["result"]["profile"] == "finance"
    assert rich["result"]["profile_label"] == "财经市场"
    assert any(r["relation"] == "acquire" for r in rich["result"]["relations"])


def test_legal_profile_adds_relations(client):
    base = client.post("/api/extract", json={"text": LEGAL_TEXT, "save": False}).json()
    rich = client.post(
        "/api/extract", json={"text": LEGAL_TEXT, "save": False, "profile": "legal"}
    ).json()
    assert base["result"]["relations"] == []
    assert any(r["relation"] == "sue" for r in rich["result"]["relations"])


def test_unknown_profile_rejected(client):
    r = client.post("/api/extract", json={"text": FINANCE_TEXT, "profile": "medical"})
    assert r.status_code == 400
    assert "未知领域包" in r.json()["detail"]


def test_profile_batch_and_trial(client):
    batch = client.post(
        "/api/extract/batch",
        json={"items": [{"text": FINANCE_TEXT}], "save": False, "profile": "finance"},
    ).json()
    assert batch["succeeded"] == 1
    assert batch["items"][0]["relation_count"] == 1

    trial = client.post(
        "/api/rules/trial",
        json={
            "text": "腾讯控股吃下搜狗公司。",
            "triggers": [{"relation_key": "acquire", "trigger": "拿下"}],
            "profile": "finance",
        },
    ).json()
    assert trial["profile"] == "finance"
    assert trial["before_count"] >= 1
    # 试跑不落库：真实自定义触发词仍为空
    assert client.get("/api/rules").json()["items"] == []


def test_profile_merge_does_not_mutate_inputs():
    terms = [{"text": "自定义机构", "type": "ORG"}]
    triggers = {"acquire": ["拿下"]}
    merged_terms, merged_triggers = domain_profiles.merge(terms, triggers, "finance")
    assert terms == [{"text": "自定义机构", "type": "ORG"}]
    assert triggers == {"acquire": ["拿下"]}
    assert len(merged_terms) > len(terms)
    assert "吃下" in merged_triggers["acquire"] and "拿下" in merged_triggers["acquire"]
    general_terms, general_triggers = domain_profiles.merge(terms, triggers, "general")
    assert general_terms == terms and general_triggers == triggers


# --------------------------------------------------------------------------- #
# 静态试用数据（断网可用的前提：数据真实、结构完整、零后端依赖）
# --------------------------------------------------------------------------- #

DEMO_JSON = (
    Path(__file__).resolve().parents[2]
    / "frontend" / "src" / "data" / "demo-samples.json"
)


def test_landing_demo_samples_are_real_and_complete():
    data = json.loads(DEMO_JSON.read_text(encoding="utf-8"))
    samples = data["samples"]
    assert len(samples) >= 3
    assert len(data["catalog"]) == 19
    assert len(data["entityTypes"]) == 6
    assert len({s["profile"] for s in samples}) >= 3
    for sample in samples:
        assert sample["title"] and sample["text"]
        assert sample["relations"] and sample["entities"] and sample["sentences"]
        assert sample["stats"]["relation_count"] == len(sample["relations"])
        for rel in sample["relations"]:
            assert rel["head"] and rel["relation"] and rel["tail"]
            assert rel["evidence"]
            assert rel["explanation"]["strategy"]
        # 试用沙箱的数据必须能离线还原，不能引用网络资源
        assert "http://" not in json.dumps(sample, ensure_ascii=False)
        assert "https://" not in json.dumps(sample, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# 领域包随记录持久化：历史记录与离线报告都要能说明「这条是用什么抽的」
# --------------------------------------------------------------------------- #

def test_saved_record_keeps_profile_and_label(client):
    res = client.post(
        "/api/extract",
        json={"text": FINANCE_TEXT, "save": True, "profile": "finance"},
    ).json()
    assert res["result"]["relations"], "财经包应能命中「吃下」"
    detail = client.get(f"/api/records/{res['record_id']}").json()
    assert detail["profile"] == "finance"
    assert detail["profile_label"] == "财经市场"


def test_report_html_states_profile(client):
    res = client.post(
        "/api/extract",
        json={"text": FINANCE_TEXT, "save": True, "profile": "finance"},
    ).json()
    report = client.post("/api/report", json={"record_id": res["record_id"]}).json()
    assert "领域包" in report["html"]
    assert "财经市场" in report["html"]
