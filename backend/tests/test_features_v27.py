# -*- coding: utf-8 -*-
"""2.7.0 断言极性：否认 / 传闻 / 条件必须与事实陈述区分开。

这一组测试守的是一条产品底线：把「腾讯否认收购搜狗」抽成一条和
「腾讯收购搜狗」同样的三元组，对做信息核实的人来说比漏抽更糟。
"""

from __future__ import annotations

import re

from app import main
from app.nlp import polarity


def _analyze(client, text: str) -> dict:
    return client.post(
        "/api/extract", json={"text": text, "save": False, "language": "zh"}
    ).json()["result"]


def _assertions(result: dict) -> dict[str, str]:
    return {f"{r['head']}-{r['relation']}-{r['tail']}": r["assertion"] for r in result["relations"]}


# ---------- 判定单元 ----------


def test_judge_negation_variants():
    cases = [
        "腾讯控股有限公司否认收购了搜狗公司。",
        "腾讯控股有限公司并未收购搜狗公司。",
        "腾讯控股有限公司从未收购搜狗公司。",
        "公司明确否认了这起收购。",
    ]
    for text in cases:
        v = polarity.judge(text, "收购", 8, 10)
        assert v["assertion"] == "negated", text
        assert v["assertion_cue"], text


def test_judge_rumor_frames():
    for text in (
        "有消息称腾讯将收购搜狗公司。",
        "据知情人士透露，腾讯正在收购搜狗公司。",
        "网传腾讯收购搜狗公司。",
    ):
        v = polarity.judge(text, "收购", 6, 8)
        assert v["assertion"] == "rumored", text


def test_judge_conditional():
    v = polarity.judge("如果腾讯完成对搜狗的收购，交易金额将超过百亿。", "收购", 8, 10)
    assert v["assertion"] == "conditional"


def test_judge_fact_stays_fact():
    v = polarity.judge("腾讯控股有限公司宣布以35亿美元收购搜狗公司。", "收购", 8, 10)
    assert v["assertion"] == "fact"
    assert v["penalty"] == 1.0


def test_judge_is_clause_level_not_sentence_level():
    """同一句里前半是事实、后半是传闻时，两半必须判得不一样。"""
    text = (
        "腾讯控股有限公司与搜狗公司签署了技术合作协议，双方共享搜索算法。"
        "有媒体报道称腾讯将收购搜狗，但双方均未证实。"
    )
    fact_pos = text.index("签署")
    rumor_pos = text.index("收购")
    assert polarity.judge(text, "签署", fact_pos, fact_pos + 2)["assertion"] == "fact"
    assert polarity.judge(text, "收购", rumor_pos, rumor_pos + 2)["assertion"] == "rumored"


def test_judge_avoids_future_false_positive():
    """「未来」不是否定词——不能因为句子里有「未」就把事实判成否认。"""
    v = polarity.judge("公司未来三年将投资一百亿元建设新工厂。", "投资", 6, 8)
    assert v["assertion"] == "fact"


def test_judge_back_reference_refutation():
    """「该说法已被辟谣」这种后置否证要能挂回前一小句。"""
    text = "此前网传腾讯收购搜狗，该说法已被公司辟谣。"
    assert polarity.judge(text, "收购", 6, 8)["assertion"] == "negated"


def test_assertion_labels_complete():
    for key in ("fact", "negated", "rumored", "conditional"):
        assert key in polarity.ASSERTION_LABELS


# ---------- 接口输出 ----------


def test_api_exposes_assertion_fields(client):
    result = _analyze(client, "9月5日，腾讯控股宣布收购搜狗公司。")
    assert result["relations"]
    for r in result["relations"]:
        for field in ("assertion", "assertion_label", "assertion_cue", "assertion_clause"):
            assert field in r
        assert r["assertion"] in polarity.ASSERTION_LABELS


def test_negated_relation_gets_confidence_penalty(client):
    fact = _analyze(client, "腾讯控股有限公司宣布收购搜狗公司。")["relations"][0]
    negated = _analyze(client, "腾讯控股有限公司否认收购搜狗公司。")["relations"][0]
    assert negated["assertion"] == "negated"
    assert negated["confidence"] < fact["confidence"]
    assert negated["score_parts"].get("polarity", 1.0) < 1.0


def test_stats_split_fact_and_non_fact(client):
    result = _analyze(
        client,
        "腾讯控股有限公司与搜狗公司签署了技术合作协议。"
        "有媒体报道称腾讯将收购搜狗，但双方均未证实。",
    )
    stats = result["stats"]
    assert stats["relation_count"] == stats["fact_relation_count"] + stats["non_fact_relation_count"]
    assert stats["fact_relation_count"] >= 1
    assert stats["non_fact_relation_count"] >= 1
    assert set(stats["assertion_counts"]) <= set(polarity.ASSERTION_LABELS)


def test_pure_negation_yields_no_fact_relation(client):
    result = _analyze(client, "针对市场传闻，腾讯控股有限公司今日明确否认收购搜狗公司。")
    assert result["stats"]["fact_relation_count"] == 0


# ---------- 评测口径 ----------


def test_eval_excludes_non_fact_from_predictions(client):
    """否认 / 传闻抽出的关系不计入预测，否则「抽对了个假命题」会被算成正确。"""
    report = client.post("/api/eval", json={"save": False}).json()["report"]
    assert "excluded_non_fact" in report
    assert report["excluded_non_fact"] >= 1
    # 负例用例不允许出现误抽
    negatives = [c for c in report["per_case"] if "负例" in c["title"]]
    assert len(negatives) >= 6
    assert all(c["fp"] == 0 for c in negatives), negatives


# ---------- 英文同 schema ----------


def test_english_polarity_matches_chinese_schema():
    from app.nlp.english import analyze_en  # noqa: PLC0415

    try:
        result = analyze_en("Tencent reportedly plans to acquire Sogou Inc.")
    except RuntimeError:
        import pytest

        pytest.skip("未安装 spaCy 英文模型")
    for r in result["relations"]:
        assert r["assertion"] in polarity.ASSERTION_LABELS
        assert "assertion_label" in r


def test_english_negation_judged():
    v = polarity.judge_en("Tencent denied that it acquired Sogou.")
    assert v["assertion"] == "negated"
    v = polarity.judge_en("If Tencent acquires Sogou, the deal would exceed $1 billion.")
    assert v["assertion"] == "conditional"
    v = polarity.judge_en("Tencent acquired Sogou in 2021.")
    assert v["assertion"] == "fact"


# ---------- 版本与金标准 ----------


def test_version_and_gold_scale(client):
    assert re.fullmatch(r"\d+\.\d+\.\d+", main.VERSION)
    assert client.get("/api/health").json()["version"] == main.VERSION
    gold = client.get("/api/eval/gold").json()
    assert gold["total"] >= 30
