# -*- coding: utf-8 -*-
"""2.4.0 英文本地化引擎：spaCy NER + 依存句法，双引擎同 schema。"""

from __future__ import annotations

import pytest

from app.nlp import english, pipeline


# --------------------------------------------------------------------------- #
# 模型可用性：没装 spaCy 的环境也要能跑完整测试套件
# --------------------------------------------------------------------------- #

def test_available_is_bool_and_non_throwing():
    """available() 永不抛异常，返回布尔值。"""
    result = english.available()
    assert isinstance(result, bool)


def test_engine_error_is_string():
    assert isinstance(english.engine_error(), str)


# --------------------------------------------------------------------------- #
# 以下用例需要 en_core_web_sm；缺失时整体跳过，不影响中文链路测试
# --------------------------------------------------------------------------- #

pytestmark_requires_model = pytest.mark.skipif(
    not english.available(), reason="en_core_web_sm 未安装"
)


@pytestmark_requires_model
def test_acquire_relation():
    r = english.analyze_en("Apple acquired Sogou Inc. in 2021.")
    rels = [(x["head"], x["relation"], x["tail"]) for x in r["relations"]]
    assert ("Apple", "acquire", "Sogou Inc.") in rels


@pytestmark_requires_model
def test_ceo_pattern():
    """X is the CEO of Y -> employ(PERSON->ORG)，职位句式模板。"""
    r = english.analyze_en("Sundar Pichai is the CEO of Google.")
    assert any(
        x["relation"] == "employ" and x["head"] == "Sundar Pichai" and x["tail"] == "Google"
        for x in r["relations"]
    )


@pytestmark_requires_model
def test_became_ceo_pattern():
    r = english.analyze_en("Sundar Pichai became CEO of Alphabet.")
    assert any(x["relation"] == "employ" for x in r["relations"])


@pytestmark_requires_model
def test_found_and_headquarter_with_passive():
    """被动句 Alibaba is headquartered in Hangzhou 不能方向倒挂。"""
    r = english.analyze_en("Jack Ma founded Alibaba in 1999. Alibaba is headquartered in Hangzhou.")
    rels = {(x["head"], x["relation"], x["tail"]) for x in r["relations"]}
    assert ("Jack Ma", "found", "Alibaba") in rels
    assert ("Alibaba", "headquarter", "Hangzhou") in rels
    # 绝不能出现 Hangzhou -> Alibaba 的倒挂
    assert ("Hangzhou", "headquarter", "Alibaba") not in rels


@pytestmark_requires_model
def test_org_type_correction():
    """小模型把公司误判为地名时要纠正：Epic Games / Alibaba -> ORG。"""
    r = english.analyze_en("Tencent invested in Epic Games.")
    epic = [e for e in r["entities"] if "Epic" in e["text"]]
    assert epic and epic[0]["type"] == "ORG"


@pytestmark_requires_model
def test_schema_parity_with_chinese():
    """英文结果与中文 schema 逐字段对齐（只多 language/engine 元信息）。"""
    r = english.analyze_en("Apple acquired Sogou Inc.")
    assert r["language"] == "en" and r["engine"] == "spacy"
    for key in ("text", "sentences", "entities", "relations", "stats",
                "entity_type_counts", "relation_type_counts"):
        assert key in r
    if r["entities"]:
        assert {"id", "text", "canonical", "type", "type_label", "color",
                "start", "end", "sentence_index", "source", "confidence"} <= set(r["entities"][0])
    if r["relations"]:
        rel_keys = set(r["relations"][0])
        assert {"head", "tail", "relation", "relation_label", "relation_color",
                "confidence", "evidence", "sentence_index", "trigger",
                "rule_base", "score_parts", "explanation"} <= rel_keys
        assert {"strategy", "steps", "confidence_parts"} <= set(r["relations"][0]["explanation"])


@pytestmark_requires_model
def test_deterministic():
    """同文本两次抽取逐字一致。"""
    text = "Apple acquired Sogou Inc. Sundar Pichai is the CEO of Google."
    a = english.analyze_en(text)
    b = english.analyze_en(text)
    assert a["relations"] == b["relations"]
    assert a["entities"] == b["entities"]


@pytestmark_requires_model
def test_pipeline_language_routing():
    """pipeline.analyze(language='en') 走英文引擎，输出带 language=en。"""
    r = pipeline.analyze("Apple acquired Sogou Inc.", language="en")
    assert r["language"] == "en"
    assert any(x["relation"] == "acquire" for x in r["relations"])


@pytestmark_requires_model
def test_pipeline_default_is_chinese():
    """不传 language 时仍走中文引擎（零回归）。"""
    r = pipeline.analyze("腾讯收购搜狗公司。")
    assert "language" not in r or r["language"] != "en"


@pytestmark_requires_model
def test_relation_label_and_color_reuse():
    """英文关系的中文标签与配色复用 RELATION_MAP，前端无需区分。"""
    from app.nlp.lexicon import RELATION_MAP
    r = english.analyze_en("Apple acquired Sogou Inc.")
    acq = next(x for x in r["relations"] if x["relation"] == "acquire")
    assert acq["relation_label"] == RELATION_MAP["acquire"].label
    assert acq["relation_color"] == RELATION_MAP["acquire"].color


# --------------------------------------------------------------------------- #
# API 层（client fixture 隔离临时库）
# --------------------------------------------------------------------------- #

@pytestmark_requires_model
def test_api_extract_english(client):
    resp = client.post("/api/extract", json={
        "text": "Apple acquired Sogou Inc. in 2021.",
        "save": False,
        "language": "en",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"]["language"] == "en"
    assert any(x["relation"] == "acquire" for x in body["result"]["relations"])


def test_api_extract_invalid_language(client):
    resp = client.post("/api/extract", json={
        "text": "Apple acquired Sogou.", "save": False, "language": "fr",
    })
    assert resp.status_code == 400


def test_health_exposes_dual_engine(client):
    h = client.get("/api/health").json()
    assert "engines" in h
    assert "zh" in h["engines"] and "en" in h["engines"]
    assert h["engines"]["zh"]["available"] is True
